"""Tests for CORS middleware configuration in backend/main.py.

Tests (2 total):
1. test_cors_preflight_allows_configured_origin - OPTIONS preflight returns 200
   with access-control-allow-origin matching the configured FRONTEND_ORIGIN.
2. test_cors_allows_post_method - access-control-allow-methods includes POST.

Implementation note: importing `main` triggers router imports that require
ENCRYPTION_KEY and DATABASE_URL env vars at import time (see test_projects.py
for the established pattern). Set them before importing.
"""

import os

from cryptography.fernet import Fernet

# Set env vars BEFORE importing any app modules.
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def test_cors_preflight_allows_configured_origin() -> None:
    """OPTIONS /api/projects preflight must succeed (200, not 405) and echo the
    configured origin in access-control-allow-origin."""
    response = client.options(
        "/api/projects",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_allows_post_method() -> None:
    """access-control-allow-methods response header must include POST."""
    response = client.options(
        "/api/projects",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "POST" in response.headers.get("access-control-allow-methods", "")
