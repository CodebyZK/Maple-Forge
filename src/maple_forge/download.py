"""Download source data for Maple Forge."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from maple_forge import config
from maple_forge.io import write_json_atomic

LOGGER = logging.getLogger(__name__)
DOWNLOAD_BLOCK_SIZE = 1024 * 1024
REQUEST_TIMEOUT = (15, 300)
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


class DownloadResponse(Protocol):
    """Subset of a requests response used by the downloader."""

    def __enter__(self) -> DownloadResponse: ...

    def __exit__(self, *args: object) -> None: ...

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int) -> Iterator[bytes]: ...


HttpGet = Callable[..., DownloadResponse]


def resolve_source_url(explicit_url: str | None = None) -> str:
    """Resolve the CSV URL from a CLI value, environment, or project default."""
    return (
        explicit_url
        or os.getenv(config.GRANTS_CSV_URL_ENV_VAR)
        or config.DEFAULT_GRANTS_CSV_URL
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_retry_session() -> requests.Session:
    """Create an HTTP session that retries temporary connection/status failures."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=RETRYABLE_STATUS_CODES,
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    return session


def download_grants(
    source_url: str | None = None,
    destination: Path = config.RAW_GRANTS_CSV,
    metadata_path: Path = config.RAW_METADATA_JSON,
    *,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    """Stream the grants CSV to disk and persist retrieval metadata."""
    resolved_url = resolve_source_url(source_url)
    if urlparse(resolved_url).scheme.lower() != "https":
        raise ValueError("grants source URL must use HTTPS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(f"{destination.suffix}.part")
    digest = hashlib.sha256()
    byte_count = 0
    session = _build_retry_session() if http_get is None else None
    request = session.get if session is not None else http_get

    LOGGER.info("Downloading grants CSV from %s", resolved_url)
    try:
        with request(
            resolved_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as output:
                for block in response.iter_content(chunk_size=DOWNLOAD_BLOCK_SIZE):
                    if not block:
                        continue
                    output.write(block)
                    digest.update(block)
                    byte_count += len(block)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
        if session is not None:
            session.close()

    metadata: dict[str, Any] = {
        "byte_count": byte_count,
        "retrieved_at": _utc_now(),
        "sha256": digest.hexdigest(),
        "source_url": resolved_url,
    }
    write_json_atomic(metadata_path, metadata, sort_keys=True)
    LOGGER.info("Downloaded %s bytes to %s", f"{byte_count:,}", destination)
    return metadata


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download the federal grants CSV.")
    parser.add_argument("--url", help="Override the official CSV resource URL.")
    parser.add_argument(
        "--output",
        type=Path,
        default=config.RAW_GRANTS_CSV,
        help="CSV destination path.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=config.RAW_METADATA_JSON,
        help="Retrieval metadata destination path.",
    )
    return parser


def main() -> None:
    """CLI entry point for downloading source data."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()
    download_grants(args.url, args.output, args.metadata)
