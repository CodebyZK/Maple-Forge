from pathlib import Path

import maple_forge
from maple_forge import config


def test_package_has_version() -> None:
    assert maple_forge.__version__ == "0.1.0"


def test_project_root_exists() -> None:
    assert isinstance(config.PROJECT_ROOT, Path)
    assert config.PROJECT_ROOT.exists()


def test_sample_size_is_500() -> None:
    assert config.SAMPLE_SIZE == 500
