"""Shared fixtures for ai-update-monitor tests."""

import os
import tempfile

import pytest

from app.db import init_db


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary SQLite database for testing."""
    path = str(tmp_path / "test.db")
    init_db(path)
    return path
