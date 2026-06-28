"""Shared pytest setup for the MongoDB-backed backend.

Replaces the old per-file in-memory SQLite + StaticPool fixtures. A single
in-process mongomock client stands in for MongoDB, so DB-touching tests need no
running server. The autouse fixture clears all collections and recreates indexes
before every test for full isolation.

Because get_db()/get_database() resolve the client through database._client, we
only have to swap that one global here — the real get_db dependency then yields
the mongomock database, so no FastAPI dependency override for the DB is needed.
"""

import os

from cryptography.fernet import Fernet

# Env must be set before any app module is imported.
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MONGODB_DB", "aisdlc_test")
os.environ.setdefault("JWT_SECRET_KEY", "x" * 32)
os.environ.setdefault("API_TOKEN", "test-token")

import mongomock  # noqa: E402
import pytest  # noqa: E402

import database  # noqa: E402

# Point the whole app at an in-process fake Mongo.
database._client = mongomock.MongoClient()

from database import get_database, init_indexes  # noqa: E402
from main import app  # noqa: E402
from services.auth import get_current_user  # noqa: E402

# DB-touching tests focus on behavior, not auth — stub the authenticated user.
app.dependency_overrides[get_current_user] = lambda: "test-admin"


@pytest.fixture(autouse=True)
def _reset_mongo():
    """Drop all collections and rebuild indexes before each test for isolation."""
    db = get_database()
    for name in db.list_collection_names():
        db.drop_collection(name)
    init_indexes(db)
    yield


@pytest.fixture
def db():
    """The mongomock Database handle (same one the app uses)."""
    return get_database()


@pytest.fixture
def client():
    """A TestClient bound to the app (auth stubbed in conftest)."""
    from fastapi.testclient import TestClient

    return TestClient(app)
