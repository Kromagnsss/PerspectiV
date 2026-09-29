from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).resolve().parent.parent / "data" / "perspectiv-api-test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["PERSPECTIV_AUTH_DISABLED"] = "true"
os.environ["PERSPECTIV_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["PERSPECTIV_ENV"] = "test"


@pytest.fixture(scope="session")
def client():
    from perspectiv.api import app

    with TestClient(app) as test_client:
        yield test_client
