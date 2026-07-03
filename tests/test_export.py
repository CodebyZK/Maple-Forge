import json
from pathlib import Path

from maple_forge.export import export_sample

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
    assert any(record["recipient_name"] == "NA" for record in records)
    assert rejected[0]["errors"] == ["recipient_name is required"]
