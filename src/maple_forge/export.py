"""Export normalized Maple Forge datasets."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from maple_forge import config
from maple_forge.clean import clean_chunk
from maple_forge.io import write_json_atomic
from maple_forge.validate import RejectedRecord, validate_records

LOGGER = logging.getLogger(__name__)

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("record_id", pa.string()),
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


@dataclass(frozen=True)
class ExportSummary:
    """Counts and paths produced by a sample export."""

    accepted_count: int
    duplicate_count: int
    rejected_count: int
    sample_count: int
    output_path: Path
    rejected_path: Path


@dataclass(frozen=True)
class BuildSummary:
    """Counts and paths produced by a complete pipeline build."""

    accepted_count: int
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_artifact(path: Path, row_count: int) -> dict[str, Any]:
    try:
        display_path = path.resolve().relative_to(config.PROJECT_ROOT.resolve())
    except ValueError:
        display_path = Path(path.name)
    return {
        "path": display_path.as_posix(),
        "row_count": row_count,
        "sha256": _sha256(path),
    }


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
    accepted_count = 0
    duplicate_count = 0
    rejected_count = 0

    LOGGER.info("Processing %s in chunks of %s rows", input_csv, f"{chunk_size:,}")
    try:
        with rejected_temporary.open("w", encoding="utf-8", newline="\n") as rejected:
            chunks = pd.read_csv(
                input_csv,
                chunksize=chunk_size,
                dtype=str,
                encoding="utf-8-sig",
                keep_default_na=False,
                na_values=[""],
            )
            for frame in chunks:
                validation = validate_records(
                    clean_chunk(
                        frame,
                        source_url=source_url,
                        retrieved_at=retrieved_at,
                    )
                )
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
                    _add_to_sample(sample_heap, record, sample_size)
        rejected_temporary.replace(rejected_path)
    finally:
        rejected_temporary.unlink(missing_ok=True)

    sample = _sample_records(sample_heap)
    write_json_atomic(output_path, sample, ensure_ascii=False)
    return ExportSummary(
        accepted_count=accepted_count,
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
    rejected_temporary = rejected_path.with_suffix(f"{rejected_path.suffix}.part")
    sample_heap: list[tuple[int, str, dict[str, Any]]] = []
    accepted_ids: set[str] = set()
    accepted_count = 0
    duplicate_count = 0
    rejected_count = 0
    writer: pq.ParquetWriter | None = None

    LOGGER.info("Building full dataset from %s", input_csv)
    try:
        writer = pq.ParquetWriter(parquet_temporary, PARQUET_SCHEMA)
        with rejected_temporary.open("w", encoding="utf-8", newline="\n") as rejected:
            chunks = pd.read_csv(
                input_csv,
                chunksize=chunk_size,
                dtype=str,
                encoding="utf-8-sig",
                keep_default_na=False,
                na_values=[""],
            )
            for chunk_number, frame in enumerate(chunks, start=1):
                validation = validate_records(
                    clean_chunk(
                        frame,
                        source_url=source_url,
                        retrieved_at=retrieved_at,
                    )
                )
                for item in validation.rejected:
                    _write_rejected(rejected, item)
                    rejected_count += 1

                unique_records: list[dict[str, Any]] = []
                for record in validation.accepted:
                    record_id = str(record["record_id"])
                    if record_id in accepted_ids:
                        duplicate_count += 1
                        continue
                    accepted_ids.add(record_id)
                    unique_records.append(record)
                    accepted_count += 1
                    _add_to_sample(sample_heap, record, sample_size)

                if unique_records:
                    writer.write_table(
                        pa.Table.from_pylist(
                            [_parquet_record(record) for record in unique_records],
                            schema=PARQUET_SCHEMA,
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
        parquet_temporary.replace(parquet_path)
        rejected_temporary.replace(rejected_path)
    finally:
        if writer is not None:
            writer.close()
        parquet_temporary.unlink(missing_ok=True)
        rejected_temporary.unlink(missing_ok=True)

    sample = _sample_records(sample_heap)
    write_json_atomic(sample_path, sample, ensure_ascii=False)
    manifest = {
        "schema_version": config.SCHEMA_VERSION,
        "source": {
            key: metadata[key]
            for key in ("source_url", "retrieved_at", "byte_count", "sha256")
            if key in metadata
        },
        "counts": {
            "accepted": accepted_count,
            "duplicates": duplicate_count,
            "rejected": rejected_count,
            "sample": len(sample),
        },
        "artifacts": {
            "parquet": _manifest_artifact(parquet_path, accepted_count),
            "sample": _manifest_artifact(sample_path, len(sample)),
            "rejections": _manifest_artifact(rejected_path, rejected_count),
        },
    }
    write_json_atomic(manifest_path, manifest, ensure_ascii=False, sort_keys=True)

    LOGGER.info(
        "Built %s records, %s sample records, and %s rejection reports",
        f"{accepted_count:,}",
        f"{len(sample):,}",
        f"{rejected_count:,}",
    )
    return BuildSummary(
        accepted_count=accepted_count,
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
