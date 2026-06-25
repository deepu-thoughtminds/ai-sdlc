"""Tests for JWT authentication (services/auth.py + routers/auth.py).

Covered:
  - POST /api/auth/login with good creds → 200 + bearer token
  - POST /api/auth/login with bad creds → 401
  - protected route (GET /api/auth/me) without a token → 401
  - protected route with a valid token → 200 + username
  - protected route with a garbage token → 401
  - protected route with an expired token → 401

These tests exercise the REAL get_current_user dependency. test_projects.py and
test_dashboard.py install a global override on the shared `app` object to bypass
auth; the autouse fixture below removes that override for the duration of each
test here and restores it afterward (collection order is not guaranteed).

Auth env vars are set before importing app modules (functions read them lazily).
"""

import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.fernet import Fernet

# Set env vars BEFORE importing any app modules.
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"
os.environ["JWT_EXPIRE_MINUTES"] = "720"
os.environ["AUTH_ADMIN_USERNAME"] = "admin"
os.environ["AUTH_ADMIN_PASSWORD"] = "s3cret"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from services.auth import ALGORITHM, get_current_user  # noqa: E402

client = TestClient(app)

GOOD_CREDS = {"username": "admin", "password": "s3cret"}


@pytest.fixture(autouse=True)
def use_real_auth():
    """Ensure the real get_current_user runs (drop any global override)."""
    prior = app.dependency_overrides.pop(get_current_user, None)
    yield
    if prior is not None:
        app.dependency_overrides[get_current_user] = prior


def _login_token() -> str:
    resp = client.post("/api/auth/login", json=GOOD_CREDS)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_login_good_credentials_returns_token() -> None:
    resp = client.post("/api/auth/login", json=GOOD_CREDS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_login_bad_credentials_returns_401() -> None:
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401, resp.text


def test_protected_route_without_token_returns_401() -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401, resp.text


def test_protected_route_with_valid_token_returns_200() -> None:
    token = _login_token()
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "admin"


def test_protected_route_with_garbage_token_returns_401() -> None:
    resp = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401, resp.text


def test_protected_route_with_expired_token_returns_401() -> None:
    expired = jwt.encode(
        {
            "sub": "admin",
            "exp": datetime.now(tz=timezone.utc) - timedelta(minutes=1),
        },
        os.environ["JWT_SECRET_KEY"],
        algorithm=ALGORITHM,
    )
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401, resp.text


def test_projects_endpoint_requires_auth() -> None:
    """Spot-check that a project route is actually protected (real dependency)."""
    resp = client.get("/api/projects")
    assert resp.status_code == 401, resp.text
