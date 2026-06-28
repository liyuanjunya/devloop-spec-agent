"""Pytest configuration."""

import asyncio
import sys
from pathlib import Path

import pytest

# Make devloop importable when running tests from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fixture_repo() -> Path:
    """Path to the sample_repo fixture."""
    return Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
