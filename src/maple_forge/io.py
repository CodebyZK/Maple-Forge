"""Shared filesystem helpers for Maple Forge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_atomic(
    path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = True,
    indent: int = 2,
    sort_keys: bool = False,
) -> None:
    """Write JSON through a temporary file, then atomically replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.part")
    try:
        temporary_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=ensure_ascii,
                indent=indent,
                sort_keys=sort_keys,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
