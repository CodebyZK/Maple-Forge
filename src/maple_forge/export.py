"""Export normalized Maple Forge samples."""

from __future__ import annotations

import argparse
import heapq
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from maple_forge import config
from maple_forge.clean import clean_chunk
from maple_forge.validate import RejectedRecord, validate_records

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportSummary:
    """Counts and paths produced by a sample export."""

    accepted_count: int
    duplicate_count: int
    rejected_count: int
    sample_count: int
    output_path: Path
    rejected_path: Path


def _load_metadata(path: Path) -> dict[str, Any]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    for required in ("source_url", "retrieved_at"):
        if not metadata.get(required):
            raise ValueError(f"metadata is missing required field: {required}")
    return metadata


def _write_json_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.part")
    try:
        temporary_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_rejected(output: Any, rejected: RejectedRecord) -> None:
    payload = {"errors": list(rejected.errors), "record": rejected.record}
    output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


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

    # The max-heap retains the records with the lexicographically smallest IDs.
    # IDs are hashes, so this is deterministic without depending on source order.
    sample_heap: list[tuple[int, str, dict[str, Any]]] = []
    selected_ids: set[str] = set()
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
                keep_default_na=True,
            )
            for chunk_number, frame in enumerate(chunks, start=1):
                records = clean_chunk(
                    frame,
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                )
                validation = validate_records(records)
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

                    numeric_key = int(record_id.removeprefix("grant_"), 16)
                    heap_item = (-numeric_key, record_id, record)
                    if len(sample_heap) < sample_size:
                        heapq.heappush(sample_heap, heap_item)
                        selected_ids.add(record_id)
                    elif numeric_key < -sample_heap[0][0]:
                        removed = heapq.heapreplace(sample_heap, heap_item)
                        selected_ids.remove(removed[1])
                        selected_ids.add(record_id)

                if chunk_number % 10 == 0:
                    LOGGER.info(
                        "Processed %s chunks; %s accepted, %s rejected",
                        chunk_number,
                        f"{accepted_count:,}",
                        f"{rejected_count:,}",
                    )
        rejected_temporary.replace(rejected_path)
    finally:
        rejected_temporary.unlink(missing_ok=True)

    sample = [item[2] for item in sample_heap]
    sample.sort(key=lambda record: str(record["record_id"]))
    _write_json_atomic(output_path, sample)

    LOGGER.info(
        "Wrote %s sample records; %s rejected rows reported in %s",
        f"{len(sample):,}",
        f"{rejected_count:,}",
        rejected_path,
    )
    return ExportSummary(
        accepted_count=accepted_count,
        duplicate_count=duplicate_count,
        rejected_count=rejected_count,
        sample_count=len(sample),
        output_path=output_path,
        rejected_path=rejected_path,
    )


def _build_parser() -> argparse.ArgumentParser:
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


def main() -> None:
    """CLI entry point for exporting the sample JSON file."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()
    export_sample(
        args.input,
        args.metadata,
        args.output,
        args.rejected,
        sample_size=args.sample_size,
        chunk_size=args.chunk_size,
    )
