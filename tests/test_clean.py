import hashlib

import pandas as pd

from maple_forge.clean import (
    clean_chunk,
    normalize_column_name,
)


def test_normalize_column_name() -> None:
    assert normalize_column_name(" Agreement Value (CAD) ") == "agreement_value_cad"


def test_clean_chunk_parses_money_and_dates_safely() -> None:
    frame = pd.DataFrame(
        {
            "ref_number": ["one", "two", "three"],
            "agreement_value": ["$1,234.50", "(200)", "not available"],
            "agreement_start_date": [
                "2025-01-31",
                "2025-02-01",
                "not a date",
            ],
        }
    )

    records = clean_chunk(
        frame,
        source_url="https://example.test/grants.csv",
        retrieved_at="2026-07-02T12:00:00Z",
    )

    assert [record["agreement_value"] for record in records] == [
        1234.5,
        -200.0,
        None,
    ]
    assert [record["agreement_start_date"] for record in records] == [
        "2025-01-31",
        "2025-02-01",
        None,
    ]


def test_clean_chunk_maps_schema() -> None:
    source = {
        "ref_number": "001-2025-2026-Q1-00001",
        "amendment_number": "0",
        "Recipient Legal Name": "  Example   Society ",
        "Agreement Title En": "A useful project",
        "Agreement Value": "$25,000.00",
        "Agreement Start Date": "2025-04-01",
        "Agreement End Date": "",
        "Recipient Province": "Ontario",
        "Recipient City": " Ottawa ",
        "Owner Org": "tbs-sct",
        "Owner Org Title": "Treasury Board Secretariat | Secrétariat du Conseil",
        "Prog Name En": "Community Program",
        "Description En": "  Public   project purpose. ",
    }
    frame = pd.DataFrame([source, source])

    records = clean_chunk(
        frame,
        source_url="https://example.test/grants.csv",
        retrieved_at="2026-07-02T12:00:00Z",
    )

    assert len(records) == 2
    record = records[0]
    identity = "goc-grants:001-2025-2026-Q1-00001:0"
    expected_id = f"grant_{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
    assert record["record_id"] == expected_id
    assert record["recipient_name"] == "Example Society"
    assert record["agreement_value"] == 25_000.0
    assert record["agreement_end_date"] is None
    assert record["province"] == "ON"
    assert record["department"] == "Treasury Board Secretariat"
    assert record["description"] == "Public project purpose."
    assert records[0] == records[1]


def test_record_id_distinguishes_amendments() -> None:
    base = {
        "ref_number": "001-2025-2026-Q1-00001",
        "recipient_legal_name": "Recipient",
        "agreement_title_en": "Project",
        "agreement_value": "100",
        "owner_org": "org",
        "owner_org_title": "Organization",
        "description_en": "Purpose",
    }
    frame = pd.DataFrame(
        [
            {**base, "amendment_number": "0"},
            {**base, "amendment_number": "1"},
        ]
    )

    records = clean_chunk(
        frame,
        source_url="https://example.test/grants.csv",
        retrieved_at="2026-07-02T12:00:00Z",
    )

    assert records[0]["record_id"] != records[1]["record_id"]


def test_clean_chunk_uses_program_fields_when_record_text_is_missing() -> None:
    frame = pd.DataFrame(
        [
            {
                "ref_number": "fallback-record",
                "recipient_legal_name": "Example Recipient",
                "agreement_value": "1000",
                "owner_org_title": "Example Department",
                "prog_name_en": "Community Program",
                "prog_purpose_en": "Supports community projects.",
            }
        ]
    )

    record = clean_chunk(
        frame,
        source_url="https://example.test/grants.csv",
        retrieved_at="2026-07-02T12:00:00Z",
    )[0]

    assert record["agreement_title"] == "Community Program"
    assert record["description"] == "Supports community projects."


def test_clean_chunk_uses_description_as_final_title_fallback() -> None:
    frame = pd.DataFrame(
        [
            {
                "ref_number": "description-title",
                "recipient_legal_name": "Example Recipient",
                "agreement_value": "1000",
                "owner_org_title": "Example Department",
                "description_en": "Published project description.",
            }
        ]
    )

    record = clean_chunk(
        frame,
        source_url="https://example.test/grants.csv",
        retrieved_at="2026-07-02T12:00:00Z",
    )[0]

    assert record["agreement_title"] == "Published project description."


def test_clean_chunk_treats_malformed_optional_date_as_missing() -> None:
    frame = pd.DataFrame(
        {
            "ref_number": ["bad-date"],
            "agreement_end_date": ["209-10-16"],
        }
    )

    record = clean_chunk(
        frame,
        source_url="https://example.test/grants.csv",
        retrieved_at="2026-07-02T12:00:00Z",
    )[0]

    assert record["agreement_end_date"] is None
