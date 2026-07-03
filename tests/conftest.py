"""Shared pytest configuration."""

from pathlib import Path
from uuid import uuid4

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Use a fresh project-local temp directory on every test run."""
    if config.option.basetemp is None:
        config.option.basetemp = Path("build") / f"pytest-{uuid4().hex}"
