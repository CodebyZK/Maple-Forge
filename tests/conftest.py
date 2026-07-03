"""Shared pytest configuration."""

import shutil
from pathlib import Path
from uuid import uuid4

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Use a fresh project-local temp directory on every test run."""
    if config.option.basetemp is None:
        config.option.basetemp = Path(f".pytest-tmp-{uuid4().hex}")


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Remove the project-local temp directory after the test run."""
    if session.config.option.basetemp is not None:
        shutil.rmtree(session.config.option.basetemp, ignore_errors=True)
