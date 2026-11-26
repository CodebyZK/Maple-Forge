import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from maple_forge import config
from maple_forge.export import _publish_files, build_dataset, export_sample

CSV_TEXT = """ref_number,amendment_number,recipient_legal_name,agreement_title_en,agreement_value,agreement_start_date,agreement_end_date,recipient_province,recipient_city,prog_name_en,description_en,owner_org,owner_org_title
001-2025-2026-Q1-00001,0,NA,Alpha Project,1000,2025-04-01,2026-03-31,ON,Ottawa,Program A,Alpha purpose,dept-a,Department A
001-2025-2026-Q1-00002,0,Beta Society,Beta Project,2000,2025-05-01,,Quebec,Montreal,Program B,Beta purpose,dept-b,Department B
001-2025-2026-Q1-00003,0,Gamma Society,Gamma Project,3000,,,British Columbia,Vancouver,,Gamma purpose,dept-c,Department C
001-2025-2026-Q1-00003,0,Gamma Society,Gamma Project,3000,,,British Columbia,Vancouver,,Gamma purpose,dept-c,Department C
001-2025-2026-Q1-00004,0,,Invalid Project,4000,2025-01-01,,AB,Calgary,Program D,Invalid recipient,dept-d,Department D
"""


def test_export_sample_is_deterministic_and_reports_rejections(
    tmp_path: Path,
) -> None:
    input_csv = tmp_path / "grants.csv"
    metadata_path = tmp_path / "grants.metadata.json"
    output_path = tmp_path / "grants.sample.json"
    rejected_path = tmp_path / "grants.rejected.jsonl"
    input_csv.write_text(CSV_TEXT, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/grants.csv",
                "retrieved_at": "2026-07-02T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    first = export_sample(
        input_csv,
        metadata_path,
        output_path,
        rejected_path,
        sample_size=2,
        chunk_size=2,
    )
    first_bytes = output_path.read_bytes()
    second = export_sample(
        input_csv,
        metadata_path,
        output_path,
        rejected_path,
        sample_size=2,
        chunk_size=3,
    )

    records = json.loads(output_path.read_text(encoding="utf-8"))
    rejected = [
        json.loads(line)
        for line in rejected_path.read_text(encoding="utf-8").splitlines()
    ]
    assert first.sample_count == second.sample_count == 2
    assert first.accepted_count == second.accepted_count == 3
    assert first.duplicate_count == second.duplicate_count == 1
    assert first.rejected_count == second.rejected_count == 1
    assert output_path.read_bytes() == first_bytes
    assert [record["record_id"] for record in records] == sorted(
        record["record_id"] for record in records
    )
    assert first.agreement_count == 3
    assert all(record["is_latest_amendment"] for record in records)
    assert all(record["amendment_count"] == 1 for record in records)
    assert rejected[0]["errors"] == ["recipient_name is required"]


def test_build_dataset_writes_all_artifacts_and_manifest(tmp_path: Path) -> None:
    input_csv = tmp_path / "grants.csv"
    metadata_path = tmp_path / "grants.metadata.json"
    parquet_path = tmp_path / "grants.parquet"
    sample_path = tmp_path / "grants.sample.json"
    rejected_path = tmp_path / "grants.rejected.jsonl"
    manifest_path = tmp_path / "grants.manifest.json"
    input_csv.write_text(CSV_TEXT, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "byte_count": len(CSV_TEXT.encode("utf-8")),
                "source_url": "https://example.test/grants.csv",
                "retrieved_at": "2026-07-02T12:00:00Z",
                "sha256": "source-checksum",
            }
        ),
        encoding="utf-8",
    )

    summary = build_dataset(
        input_csv,
        metadata_path,
        parquet_path,
        sample_path,
        rejected_path,
        manifest_path,
        sample_size=2,
        chunk_size=2,
    )

    records = pd.read_parquet(parquet_path).to_dict(orient="records")
    parquet_schema = pq.read_schema(parquet_path)
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    rejected = rejected_path.read_text(encoding="utf-8").splitlines()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary.accepted_count == 3
    assert summary.duplicate_count == 1
    assert summary.rejected_count == 1
    assert summary.sample_count == 2
    assert len(records) == 3
    assert {record["recipient_name"] for record in records} == {
        "NA",
        "Beta Society",
        "Gamma Society",
    }
    assert parquet_schema.field("agreement_start_date").type == pa.date32()
    assert parquet_schema.field("retrieved_at").type == pa.timestamp("ms", tz="UTC")
    assert len(sample) == 2
    assert len(rejected) == 1
    assert manifest["schema_version"] == config.SCHEMA_VERSION
    assert manifest["source"]["source_url"] == "https://example.test/grants.csv"
    assert manifest["counts"] == {
        "accepted": 3,
        "agreements": 3,
        "duplicates": 1,
        "rejected": 1,
        "sample": 2,
    }
    assert manifest["artifacts"]["parquet"]["row_count"] == 3
    assert manifest["artifacts"]["parquet"]["sha256"] == hashlib.sha256(
        parquet_path.read_bytes()
    ).hexdigest()
    assert manifest["artifacts"]["sample"]["sha256"] == hashlib.sha256(
        sample_path.read_bytes()
    ).hexdigest()
    assert manifest["artifacts"]["rejections"]["sha256"] == hashlib.sha256(
        rejected_path.read_bytes()
    ).hexdigest()


def test_build_dataset_handles_many_unique_records_in_chunks(tmp_path: Path) -> None:
    row_count = 2_500
    input_csv = tmp_path / "grants.csv"
    metadata_path = tmp_path / "grants.metadata.json"
    header = CSV_TEXT.splitlines()[0]
    rows = [
        f"{index},0,Recipient {index},Project {index},1000,,,,,,Purpose,dept,Dept"
        for index in range(row_count)
    ]
    input_csv.write_text("\n".join([header, *rows]), encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/grants.csv",
                "retrieved_at": "2026-07-02T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    summary = build_dataset(
        input_csv,
        metadata_path,
        tmp_path / "grants.parquet",
        tmp_path / "grants.sample.json",
        tmp_path / "grants.rejected.jsonl",
        tmp_path / "grants.manifest.json",
        sample_size=10,
        chunk_size=100,
    )

    assert summary.accepted_count == row_count
    assert pq.read_metadata(summary.parquet_path).num_rows == row_count
    assert not list(tmp_path.glob("*.dedup.sqlite"))


AMENDMENT_CSV = """ref_number,amendment_number,recipient_legal_name,agreement_title_en,agreement_value,owner_org,owner_org_title
REF-1,0,Alpha,Alpha Project,100,dept-a,Department A
REF-1,1,Alpha,Alpha Project,150,dept-a,Department A
REF-1,2,Alpha,Alpha Project,120,dept-a,Department A
REF-1,0,Beta,Beta Project,500,dept-b,Department B
REF-2,,Gamma,Gamma Project,70,dept-a,Department A
"""


def test_build_dataset_flags_latest_amendment_per_agreement(tmp_path: Path) -> None:
    input_csv = tmp_path / "grants.csv"
    metadata_path = tmp_path / "grants.metadata.json"
    input_csv.write_text(AMENDMENT_CSV, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/grants.csv",
                "retrieved_at": "2026-07-02T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    summary = build_dataset(
        input_csv,
        metadata_path,
        tmp_path / "grants.parquet",
        tmp_path / "grants.sample.json",
        tmp_path / "grants.rejected.jsonl",
        tmp_path / "grants.manifest.json",
        sample_size=5,
        chunk_size=2,
    )

    frame = pd.read_parquet(summary.parquet_path)
    latest = frame[frame["is_latest_amendment"]]
    sample = json.loads(summary.sample_path.read_text(encoding="utf-8"))
    manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))

    assert summary.accepted_count == 5
    assert summary.duplicate_count == 0
    assert summary.agreement_count == 3
    assert manifest["counts"]["agreements"] == 3
    assert latest["agreement_value"].sum() == 120 + 500 + 70
    assert frame["agreement_value"].sum() == 940
    alpha = frame[frame["recipient_name"] == "Alpha"]
    assert alpha["agreement_id"].nunique() == 1
    assert set(alpha["amendment_count"]) == {3}
    assert alpha.loc[alpha["is_latest_amendment"], "amendment_number"].tolist() == [2]
    assert frame["amendment_number"].dtype == "int32"
    assert not list(tmp_path.glob("*.stage"))
    assert sum(record["is_latest_amendment"] for record in sample) == 3
    for record in sample:
        row = frame[frame["record_id"] == record["record_id"]].iloc[0]
        assert record["is_latest_amendment"] == bool(row["is_latest_amendment"])
        assert record["amendment_count"] == int(row["amendment_count"])


def test_publish_files_restores_existing_outputs_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_staged = tmp_path / "first.staged"
    second_staged = tmp_path / "second.staged"
    first_target = tmp_path / "first.json"
    second_target = tmp_path / "second.json"
    first_staged.write_text("new first", encoding="utf-8")
    second_staged.write_text("new second", encoding="utf-8")
    first_target.write_text("old first", encoding="utf-8")
    second_target.write_text("old second", encoding="utf-8")
    original_replace = Path.replace

    def fail_second_publish(source: Path, target: Path) -> Path:
        if source == second_staged:
            raise OSError("simulated publish failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        _publish_files(
            [
                (first_staged, first_target),
                (second_staged, second_target),
            ]
        )

    assert first_target.read_text(encoding="utf-8") == "old first"
    assert second_target.read_text(encoding="utf-8") == "old second"
