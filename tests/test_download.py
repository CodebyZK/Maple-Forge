import hashlib
import json
from pathlib import Path

import pytest

from maple_forge.download import download_grants, resolve_source_url


class FakeResponse:
    def __init__(self, blocks: list[bytes], error: Exception | None = None) -> None:
        self.blocks = blocks
        self.error = error

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield from self.blocks


def test_resolve_source_url_prefers_explicit_then_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPLE_FORGE_GRANTS_CSV_URL", "https://example.test/env.csv")

    assert resolve_source_url("https://example.test/explicit.csv").endswith(
        "explicit.csv"
    )
    assert resolve_source_url() == "https://example.test/env.csv"


def test_download_grants_streams_file_and_writes_metadata(tmp_path: Path) -> None:
    content = b"column\nvalue\n"
    destination = tmp_path / "raw" / "grants.csv"
    metadata_path = tmp_path / "raw" / "grants.metadata.json"

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        assert url == "https://example.test/grants.csv"
        assert kwargs["stream"] is True
        return FakeResponse([content[:5], b"", content[5:]])

    metadata = download_grants(
        "https://example.test/grants.csv",
        destination,
        metadata_path,
        http_get=fake_get,
    )

    assert destination.read_bytes() == content
    assert metadata["byte_count"] == len(content)
    assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
    assert str(metadata["retrieved_at"]).endswith("Z")
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata
    assert not (tmp_path / "raw" / "grants.csv.part").exists()


def test_failed_download_does_not_replace_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "grants.csv"
    destination.write_bytes(b"existing")

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse([], RuntimeError("HTTP error"))

    with pytest.raises(RuntimeError, match="HTTP error"):
        download_grants(
            "https://example.test/grants.csv",
            destination,
            tmp_path / "metadata.json",
            http_get=fake_get,
        )

    assert destination.read_bytes() == b"existing"
    assert not (tmp_path / "grants.csv.part").exists()
