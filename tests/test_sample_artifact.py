import json
from pathlib import Path

from maple_forge import config
from maple_forge.validate import validate_records


def test_committed_sample_is_complete_and_valid() -> None:
    sample_path = Path(config.SAMPLE_JSON)
    records = json.loads(sample_path.read_text(encoding="utf-8"))
    record_ids = [record["record_id"] for record in records]

    assert len(records) == config.SAMPLE_SIZE
    assert len(set(record_ids)) == config.SAMPLE_SIZE
    assert record_ids == sorted(record_ids)
    assert not validate_records(records).rejected
