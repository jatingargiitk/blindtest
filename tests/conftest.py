import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "slugify"


@pytest.fixture
def example(tmp_path, monkeypatch):
    """A private copy of the slugify example, with cwd set to it."""
    dest = tmp_path / "slugify"
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns("room", "__pycache__"))
    monkeypatch.chdir(dest)
    return dest


@pytest.fixture
def py():
    return sys.executable
