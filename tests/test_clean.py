import pandas as pd

from maple_forge.clean import (
    clean_chunk,
    normalize_column_name,
    parse_date,
    parse_money,
)


def test_normalize_column_name() -> None:
    assert normalize_column_name(" Agreement Value (CAD) ") == "agreement_value_cad"


def test_parse_money_and_date_are_safe() -> None:
    assert parse_money("$1,234.50") == 1234.5
    assert parse_money("(200)") == -200.0
    assert parse_money("not available") is None
    assert parse_date("2025-01-31") == "2025-01-31"
    assert parse_date("not a date") is None


def test_clean_chunk_maps_schema() -> None:
    source = {
        "Reference Number": "001-2025-2026-Q1-00001",
        "Amendment Number": "0",
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
    assert record["record_id"].startswith("grant_")
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
