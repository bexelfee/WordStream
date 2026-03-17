"""Pytest configuration and fixtures. Set DATA_DIR before importing app."""
import os
import tempfile
from pathlib import Path

# Set test data dir before any backend import so DB and files use it
_test_data_dir = tempfile.mkdtemp(prefix="wordstream_test_")
os.environ["DATA_DIR"] = _test_data_dir

# Clear config cache so get_settings() picks up DATA_DIR
from backend.app.config import get_settings
get_settings.cache_clear()

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.db import init_db
from backend.app.main import app


@pytest.fixture
def data_dir() -> Path:
    return Path(_test_data_dir)


@pytest.fixture(autouse=True)
async def init_test_db():
    await init_db()
    yield


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
