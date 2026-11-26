"""Export normalized Maple Forge datasets."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from maple_forge import config
from maple_forge.clean import clean_chunk
from maple_forge.io import write_json_atomic
from maple_forge.validate import RejectedRecord, ValidationResult, validate_records

LOGGER = logging.getLogger(__name__)

STAGE_SCHEMA = pa.schema(
    [
        pa.field("record_id", pa.string()),
        pa.field("agreement_id", pa.string()),
        pa.field("reference_number", pa.string()),
        pa.field("amendment_number", pa.int32()),
        pa.field("recipient_name", pa.string()),
        pa.field("agreement_title", pa.string()),
        pa.field("agreement_value", pa.float64()),
        pa.field("agreement_start_date", pa.date32()),
        pa.field("agreement_end_date", pa.date32()),
        pa.field("province", pa.string()),
        pa.field("city", pa.string()),
        pa.field("department", pa.string()),
        pa.field("program_name", pa.string()),
        pa.field("description", pa.string()),
        pa.field("source_url", pa.string()),
        pa.field("retrieved_at", pa.timestamp("ms", tz="UTC")),
    ]
)

PARQUET_SCHEMA = pa.schema(
    [
        *STAGE_SCHEMA,
        pa.field("is_latest_amendment", pa.bool_()),
        pa.field("amendment_count", pa.int32()),
    ]
)

FINALIZE_BATCH_SIZE = 100_000


@dataclass(frozen=True)
class ExportSummary:
    """Counts and paths produced by a sample export."""

    accepted_count: int
    agreement_count: int
    duplicate_count: int
    rejected_count: int
    sample_count: int
    output_path: Path
    rejected_path: Path


@dataclass(frozen=True)
class BuildSummary:
    """Counts and paths produced by a complete pipeline build."""

    accepted_count: int
    agreement_count: int
    duplicate_count: int
    rejected_count: int
    sample_count: int
    parquet_path: Path
    sample_path: Path
    rejected_path: Path
    manifest_path: Path


def _load_metadata(path: Path) -> dict[str, Any]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    for required in ("source_url", "retrieved_at"):
        if not metadata.get(required):
            raise ValueError(f"metadata is missing required field: {required}")
    return metadata


def _write_rejected(output: Any, rejected: RejectedRecord) -> None:
    payload = {"errors": list(rejected.errors), "record": rejected.record}
    output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _add_to_sample(
    sample_heap: list[tuple[int, str, dict[str, Any]]],
    record: dict[str, Any],
    sample_size: int,
) -> None:
    record_id = str(record["record_id"])
    numeric_key = int(record_id.removeprefix("grant_"), 16)
    heap_item = (-numeric_key, record_id, record)
    if len(sample_heap) < sample_size:
        heapq.heappush(sample_heap, heap_item)
    elif numeric_key < -sample_heap[0][0]:
        heapq.heapreplace(sample_heap, heap_item)


def _sample_records(
    sample_heap: list[tuple[int, str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    sample = [item[2] for item in sample_heap]
    sample.sort(key=lambda record: str(record["record_id"]))
    return sample


def _parquet_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert canonical ISO strings to native Parquet date/time values."""
    converted = dict(record)
    for field in ("agreement_start_date", "agreement_end_date"):
        value = converted[field]
        converted[field] = date.fromisoformat(value) if value is not None else None
    converted["retrieved_at"] = datetime.fromisoformat(
        str(converted["retrieved_at"]).replace("Z", "+00:00")
    )
    return converted


def _amendment_flags(stage_path: Path) -> pa.Table:
    """Derive per-record amendment flags, aligned to the staged row order.

    Each amendment row restates the agreement's full value, so only the
    highest amendment number of an agreement may be counted in totals.
    """
    keys = pq.read_table(
        stage_path, columns=["record_id", "agreement_id", "amendment_number"]
    )
    keys = keys.append_column(
        "_row", pa.array(range(keys.num_rows), type=pa.int64())
    )
    totals = keys.group_by("agreement_id").aggregate(
        [("amendment_number", "max"), ("amendment_number", "count")]
    )
    joined = keys.join(totals, "agreement_id").sort_by("_row")
    return pa.table(
        {
            "record_id": joined["record_id"],
            "is_latest_amendment": pc.equal(
                joined["amendment_number"], joined["amendment_number_max"]
            ),
            "amendment_count": pc.cast(
                joined["amendment_number_count"], pa.int32()
            ),
        }
    )


def _write_final_parquet(
    stage_path: Path,
    final_path: Path,
    flags: pa.Table,
) -> None:
    """Copy staged rows into the published schema with amendment flags."""
    source = pq.ParquetFile(stage_path)
    offset = 0
    with pq.ParquetWriter(final_path, PARQUET_SCHEMA) as writer:
        for batch in source.iter_batches(batch_size=FINALIZE_BATCH_SIZE):
            rows = batch.num_rows
            batch_flags = flags.slice(offset, rows)
            staged_ids = pa.chunked_array([batch.column("record_id")])
            if not batch_flags["record_id"].equals(staged_ids):
                raise RuntimeError("amendment flags are misaligned with staged rows")
            table = pa.Table.from_batches([batch])
            table = table.append_column(
                "is_latest_amendment", batch_flags["is_latest_amendment"]
            ).append_column("amendment_count", batch_flags["amendment_count"])
            writer.write_table(table.select(PARQUET_SCHEMA.names).cast(PARQUET_SCHEMA))
            offset += rows
    if offset != flags.num_rows:
        raise RuntimeError("amendment flags do not cover every staged row")


def _annotate_sample(sample: list[dict[str, Any]], flags: pa.Table) -> None:
    sample_ids = pa.array([str(record["record_id"]) for record in sample], pa.string())
    matches = flags.filter(pc.is_in(flags["record_id"], value_set=sample_ids))
    by_id = {row["record_id"]: row for row in matches.to_pylist()}
    for record in sample:
        row = by_id[str(record["record_id"])]
        record["is_latest_amendment"] = bool(row["is_latest_amendment"])
        record["amendment_count"] = int(row["amendment_count"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_artifact(
    staged_path: Path,
    published_path: Path,
    row_count: int,
) -> dict[str, Any]:
    try:
        display_path = published_path.resolve().relative_to(
            config.PROJECT_ROOT.resolve()
        )
    except ValueError:
        display_path = Path(published_path.name)
    return {
        "path": display_path.as_posix(),
        "row_count": row_count,
        "sha256": _sha256(staged_path),
    }


def _iter_validated_chunks(
    input_csv: Path,
    *,
    source_url: str,
    retrieved_at: str,
    chunk_size: int,
) -> Iterator[ValidationResult]:
    """Yield cleaned and validated chunks from a source CSV."""
    chunks = pd.read_csv(
        input_csv,
        chunksize=chunk_size,
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False,
        na_values=[""],
    )
    for frame in chunks:
        yield validate_records(
            clean_chunk(
                frame,
                source_url=source_url,
                retrieved_at=retrieved_at,
            )
        )


def _publish_files(staged_files: list[tuple[Path, Path]]) -> None:
    """Publish a group of files and restore prior outputs if a rename fails."""
    backup_suffix = f".backup-{uuid4().hex}"
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for _, target in staged_files:
            if target.exists():
                backup = target.with_name(target.name + backup_suffix)
                target.replace(backup)
                backups[target] = backup
        for staged, target in staged_files:
            staged.replace(target)
            published.append(target)
    except Exception:
        for target in published:
            target.unlink(missing_ok=True)
        for target, backup in backups.items():
            if backup.exists():
                backup.replace(target)
        raise
    else:
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def export_sample(
    input_csv: Path = config.RAW_GRANTS_CSV,
    metadata_path: Path = config.RAW_METADATA_JSON,
    output_path: Path = config.SAMPLE_JSON,
    rejected_path: Path = config.REJECTED_JSONL,
    *,
    sample_size: int = config.SAMPLE_SIZE,
    chunk_size: int = config.CSV_CHUNK_SIZE,
) -> ExportSummary:
    """Clean and validate a CSV, then write a deterministic sample."""
    if sample_size < 1:
        raise ValueError("sample_size must be at least 1")
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    metadata = _load_metadata(metadata_path)
    source_url = str(metadata["source_url"])
    retrieved_at = str(metadata["retrieved_at"])
    rejected_path.parent.mkdir(parents=True, exist_ok=True)
    rejected_temporary = rejected_path.with_suffix(f"{rejected_path.suffix}.part")
    sample_heap: list[tuple[int, str, dict[str, Any]]] = []
    accepted_ids: set[str] = set()
    agreements: dict[str, tuple[int, int]] = {}
    accepted_count = 0
    duplicate_count = 0
    rejected_count = 0

    LOGGER.info("Processing %s in chunks of %s rows", input_csv, f"{chunk_size:,}")
    try:
        with rejected_temporary.open("w", encoding="utf-8", newline="\n") as rejected:
            chunks = _iter_validated_chunks(
                input_csv,
                source_url=source_url,
                retrieved_at=retrieved_at,
                chunk_size=chunk_size,
            )
            for validation in chunks:
                for item in validation.rejected:
                    _write_rejected(rejected, item)
                    rejected_count += 1
                for record in validation.accepted:
                    record_id = str(record["record_id"])
                    if record_id in accepted_ids:
                        duplicate_count += 1
                        continue
                    accepted_ids.add(record_id)
                    accepted_count += 1
                    agreement_id = str(record["agreement_id"])
                    amendment = int(record["amendment_number"])
                    latest, count = agreements.get(agreement_id, (amendment, 0))
                    agreements[agreement_id] = (max(latest, amendment), count + 1)
                    _add_to_sample(sample_heap, record, sample_size)
        rejected_temporary.replace(rejected_path)
    finally:
        rejected_temporary.unlink(missing_ok=True)

    sample = _sample_records(sample_heap)
    for record in sample:
        latest, count = agreements[str(record["agreement_id"])]
        record["is_latest_amendment"] = int(record["amendment_number"]) == latest
        record["amendment_count"] = count
    write_json_atomic(output_path, sample, ensure_ascii=False)
    return ExportSummary(
        accepted_count=accepted_count,
        agreement_count=len(agreements),
        duplicate_count=duplicate_count,
        rejected_count=rejected_count,
        sample_count=len(sample),
        output_path=output_path,
        rejected_path=rejected_path,
    )


def build_dataset(
    input_csv: Path = config.RAW_GRANTS_CSV,
    metadata_path: Path = config.RAW_METADATA_JSON,
    parquet_path: Path = config.PROCESSED_GRANTS_PARQUET,
    sample_path: Path = config.SAMPLE_JSON,
    rejected_path: Path = config.REJECTED_JSONL,
    manifest_path: Path = config.MANIFEST_JSON,
    *,
    sample_size: int = config.SAMPLE_SIZE,
    chunk_size: int = config.CSV_CHUNK_SIZE,
) -> BuildSummary:
    """Build the full Parquet dataset, sample, rejection report, and manifest."""
    if sample_size < 1:
        raise ValueError("sample_size must be at least 1")
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    metadata = _load_metadata(metadata_path)
    source_url = str(metadata["source_url"])
    retrieved_at = str(metadata["retrieved_at"])
    for path in (parquet_path, sample_path, rejected_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    parquet_temporary = parquet_path.with_suffix(f"{parquet_path.suffix}.part")
    stage_path = parquet_path.with_suffix(f"{parquet_path.suffix}.stage")
    sample_temporary = sample_path.with_suffix(f"{sample_path.suffix}.staged")
    rejected_temporary = rejected_path.with_suffix(f"{rejected_path.suffix}.part")
    manifest_temporary = manifest_path.with_suffix(f"{manifest_path.suffix}.staged")
    dedup_path = parquet_path.with_suffix(f"{parquet_path.suffix}.dedup.sqlite")
    sample_heap: list[tuple[int, str, dict[str, Any]]] = []
    accepted_count = 0
    duplicate_count = 0
    rejected_count = 0
    writer: pq.ParquetWriter | None = None
    dedup: sqlite3.Connection | None = None
    agreement_count = 0
    processing_complete = False

    LOGGER.info("Building full dataset from %s", input_csv)
    try:
        dedup_path.unlink(missing_ok=True)
        dedup = sqlite3.connect(dedup_path)
        dedup.execute("PRAGMA journal_mode=OFF")
        dedup.execute("PRAGMA synchronous=OFF")
        dedup.execute(
            "CREATE TABLE accepted_ids "
            "(record_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        writer = pq.ParquetWriter(stage_path, STAGE_SCHEMA)
        with rejected_temporary.open("w", encoding="utf-8", newline="\n") as rejected:
            chunks = _iter_validated_chunks(
                input_csv,
                source_url=source_url,
                retrieved_at=retrieved_at,
                chunk_size=chunk_size,
            )
            for chunk_number, validation in enumerate(chunks, start=1):
                for item in validation.rejected:
                    _write_rejected(rejected, item)
                    rejected_count += 1

                unique_records: list[dict[str, Any]] = []
                with dedup:
                    for record in validation.accepted:
                        record_id = str(record["record_id"])
                        cursor = dedup.execute(
                            "INSERT OR IGNORE INTO accepted_ids VALUES (?)",
                            (record_id,),
                        )
                        if cursor.rowcount == 0:
                            duplicate_count += 1
                            continue
                        unique_records.append(record)
                        accepted_count += 1
                        _add_to_sample(sample_heap, record, sample_size)

                if unique_records:
                    writer.write_table(
                        pa.Table.from_pylist(
                            [_parquet_record(record) for record in unique_records],
                            schema=STAGE_SCHEMA,
                        )
                    )
                if chunk_number % 10 == 0:
                    LOGGER.info(
                        "Processed %s chunks; %s accepted, %s rejected",
                        chunk_number,
                        f"{accepted_count:,}",
                        f"{rejected_count:,}",
                    )
        writer.close()
        writer = None
        dedup.close()
        dedup = None
        dedup_path.unlink(missing_ok=True)

        LOGGER.info("Deriving latest amendments for %s records", f"{accepted_count:,}")
        flags = _amendment_flags(stage_path)
        agreement_count = int(pc.sum(flags["is_latest_amendment"]).as_py() or 0)
        _write_final_parquet(stage_path, parquet_temporary, flags)
        sample = _sample_records(sample_heap)
        _annotate_sample(sample, flags)
        del flags
        processing_complete = True
    finally:
        if writer is not None:
            writer.close()
        if dedup is not None:
            dedup.close()
        dedup_path.unlink(missing_ok=True)
        stage_path.unlink(missing_ok=True)
        if not processing_complete:
            parquet_temporary.unlink(missing_ok=True)
            rejected_temporary.unlink(missing_ok=True)

    write_json_atomic(sample_temporary, sample, ensure_ascii=False)
    manifest = {
        "schema_version": config.SCHEMA_VERSION,
        "source": {
            key: metadata[key]
            for key in ("source_url", "retrieved_at", "byte_count", "sha256")
            if key in metadata
        },
        "counts": {
            "accepted": accepted_count,
            "agreements": agreement_count,
            "duplicates": duplicate_count,
            "rejected": rejected_count,
            "sample": len(sample),
        },
        "artifacts": {
            "parquet": _manifest_artifact(
                parquet_temporary, parquet_path, accepted_count
            ),
            "sample": _manifest_artifact(sample_temporary, sample_path, len(sample)),
            "rejections": _manifest_artifact(
                rejected_temporary, rejected_path, rejected_count
            ),
        },
    }
    write_json_atomic(
        manifest_temporary,
        manifest,
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        _publish_files(
            [
                (parquet_temporary, parquet_path),
                (sample_temporary, sample_path),
                (rejected_temporary, rejected_path),
                (manifest_temporary, manifest_path),
            ]
        )
    finally:
        parquet_temporary.unlink(missing_ok=True)
        sample_temporary.unlink(missing_ok=True)
        rejected_temporary.unlink(missing_ok=True)
        manifest_temporary.unlink(missing_ok=True)

    LOGGER.info(
        "Built %s records (%s agreements), %s sample records, "
        "and %s rejection reports",
        f"{accepted_count:,}",
        f"{agreement_count:,}",
        f"{len(sample):,}",
        f"{rejected_count:,}",
    )
    return BuildSummary(
        accepted_count=accepted_count,
        agreement_count=agreement_count,
        duplicate_count=duplicate_count,
        rejected_count=rejected_count,
        sample_count=len(sample),
        parquet_path=parquet_path,
        sample_path=sample_path,
        rejected_path=rejected_path,
        manifest_path=manifest_path,
    )


def _build_sample_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean, validate, and export a deterministic grants sample."
    )
    parser.add_argument("--input", type=Path, default=config.RAW_GRANTS_CSV)
    parser.add_argument("--metadata", type=Path, default=config.RAW_METADATA_JSON)
    parser.add_argument("--output", type=Path, default=config.SAMPLE_JSON)
    parser.add_argument("--rejected", type=Path, default=config.REJECTED_JSONL)
    parser.add_argument("--sample-size", type=int, default=config.SAMPLE_SIZE)
    parser.add_argument("--chunk-size", type=int, default=config.CSV_CHUNK_SIZE)
    return parser


def _build_dataset_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the full Parquet dataset and supporting artifacts."
    )
    parser.add_argument("--input", type=Path, default=config.RAW_GRANTS_CSV)
    parser.add_argument("--metadata", type=Path, default=config.RAW_METADATA_JSON)
    parser.add_argument("--parquet", type=Path, default=config.PROCESSED_GRANTS_PARQUET)
    parser.add_argument("--sample", type=Path, default=config.SAMPLE_JSON)
    parser.add_argument("--rejected", type=Path, default=config.REJECTED_JSONL)
    parser.add_argument("--manifest", type=Path, default=config.MANIFEST_JSON)
    parser.add_argument("--sample-size", type=int, default=config.SAMPLE_SIZE)
    parser.add_argument("--chunk-size", type=int, default=config.CSV_CHUNK_SIZE)
    return parser


def main() -> None:
    """CLI entry point for exporting only the sample JSON file."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_sample_parser().parse_args()
    export_sample(
        args.input,
        args.metadata,
        args.output,
        args.rejected,
        sample_size=args.sample_size,
        chunk_size=args.chunk_size,
    )


def main_build() -> None:
    """CLI entry point for building all v0.2 data artifacts."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_dataset_parser().parse_args()
    build_dataset(
        args.input,
        args.metadata,
        args.parquet,
        args.sample,
        args.rejected,
        args.manifest,
        sample_size=args.sample_size,
        chunk_size=args.chunk_size,
    )
