"""Tests for JWT verification (services/auth.py + routers/auth.py).

Static-token model: there's no login endpoint. A token is minted with
create_access_token() (what generate_token.py does) and validated by
get_current_user on every protected route.

Covered:
  - protected route (GET /api/auth/me) without a token → 401
  - with a valid token → 200 + subject
  - with a garbage token → 401
  - with an expired token → 401
  - a project route is actually protected → 401

These exercise the REAL get_current_user. Other test modules install a global
override on the shared `app` to bypass auth; the autouse fixture removes it here.
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

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from services.auth import ALGORITHM, create_access_token, get_current_user  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_real_auth():
    """Ensure the real get_current_user runs (drop any global override)."""
    prior = app.dependency_overrides.pop(get_current_user, None)
    yield
    if prior is not None:
        app.dependency_overrides[get_current_user] = prior


def test_protected_route_without_token_returns_401() -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_protected_route_with_valid_token_returns_200() -> None:
    token = create_access_token("frontend")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["subject"] == "frontend"


def test_protected_route_with_garbage_token_returns_401() -> None:
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401, resp.text


def test_protected_route_with_expired_token_returns_401() -> None:
    expired = jwt.encode(
        {"sub": "frontend", "exp": datetime.now(tz=timezone.utc) - timedelta(minutes=1)},
        os.environ["JWT_SECRET_KEY"],
        algorithm=ALGORITHM,
    )
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401, resp.text


def test_projects_endpoint_requires_auth() -> None:
    assert client.get("/api/projects").status_code == 401
