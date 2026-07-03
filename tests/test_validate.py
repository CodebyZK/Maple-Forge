from copy import deepcopy

from maple_forge.validate import validate_record, validate_records


def valid_record() -> dict[str, object]:
    return {
        "record_id": "grant_0123456789abcdef01234567",
        "recipient_name": "Example Society",
        "agreement_title": "A useful project",
        "agreement_value": 1000.0,
        "agreement_start_date": "2025-04-01",
        "agreement_end_date": None,
        "province": "ON",
        "city": "Ottawa",
        "department": "Example Department",
        "program_name": None,
        "description": "Published project purpose.",
        "source_url": "https://example.test/grants.csv",
        "retrieved_at": "2026-07-02T12:00:00Z",
    }


def test_valid_record_has_no_errors() -> None:
    assert validate_record(valid_record()) == ()


def test_invalid_record_reports_all_relevant_errors() -> None:
    record = valid_record()
    record["recipient_name"] = None
    record["agreement_value"] = float("nan")
    record["agreement_start_date"] = "April 1"
    record["retrieved_at"] = "2026-07-02 12:00:00"

    errors = validate_record(record)

    assert "recipient_name is required" in errors
    assert "agreement_value must be a finite number" in errors
    assert "agreement_start_date must be an ISO 8601 date or null" in errors
    assert "retrieved_at must be an ISO 8601 UTC datetime ending in Z" in errors


def test_validate_records_partitions_without_silent_discard() -> None:
    invalid = deepcopy(valid_record())
    invalid["department"] = ""

    result = validate_records([valid_record(), invalid])

    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].record["department"] == ""
    assert result.rejected[0].errors == ("department is required",)


def test_description_is_optional() -> None:
    record = valid_record()
    record["description"] = None

    assert validate_record(record) == ()
