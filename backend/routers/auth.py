"""Authentication endpoints.

Endpoints (mounted under the /api prefix in main.py):
  POST /api/auth/login — public; exchange admin credentials for a JWT access token.
  GET  /api/auth/me    — protected; echo back the authenticated username so the
                         frontend can confirm a stored token is still valid.

Credentials are checked against a single env-seeded admin (services/auth.py).
A real users table can replace verify_credentials later without changing the
token flow.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from models.auth import LoginRequest, TokenResponse
from services.auth import create_access_token, get_current_user, verify_credentials

logger = logging.getLogger("backend.auth")

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    """Validate credentials and return a signed JWT access token.

    Returns 401 on bad credentials. The password is never logged.
    """
    if not verify_credentials(payload.username, payload.password):
        logger.info("login failed for username=%s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(payload.username)
    logger.info("login succeeded for username=%s", payload.username)
    return TokenResponse(access_token=token)


@router.get("/auth/me")
def read_me(username: str = Depends(get_current_user)) -> dict:
    """Return the authenticated username (token validity probe for the FE)."""
    return {"username": username}
