"""JWT verification + the ``get_current_user`` FastAPI dependency used to
protect ``/api`` routes.

Design (static-token model):
  - There is no login endpoint. Instead a single long-lived HS256 token is
    generated once (see ``backend/generate_token.py``), stored in env as
    ``API_TOKEN``, and handed to the frontend. The FE sends it on every request
    as ``Authorization: Bearer <token>``.
  - The backend still validates it as a real JWT — signature check against
    ``JWT_SECRET_KEY`` — so a tampered/forged token is rejected. Nothing is
    stored server-side; validation is pure signature math.

Env vars (read lazily inside functions so tests can set them before import,
mirroring services/crypto.py):
  JWT_SECRET_KEY     required — HMAC signing secret; functions raise if unset.
  JWT_EXPIRE_MINUTES optional — default lifetime for create_access_token (min).
  API_TOKEN          the generated token handed to the FE (not read here for
                     validation — kept in env purely as the canonical copy to
                     share; any token signed with JWT_SECRET_KEY is accepted).

Security notes:
  - The signing secret is never logged.
  - To revoke the FE's token, rotate JWT_SECRET_KEY and re-issue.
"""

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 720  # 12 hours
# Default lifetime for a generated static/frontend token: 10 years.
STATIC_TOKEN_MINUTES = 60 * 24 * 365 * 10

# HTTPBearer (not OAuth2PasswordBearer) so Swagger's Authorize dialog shows a
# single "paste your token" box. auto_error=False lets us return 401 (not
# HTTPBearer's default 403) for a missing/malformed Authorization header.
bearer_scheme = HTTPBearer(auto_error=False)


def _secret_key() -> str:
    """Return the JWT signing secret, raising a clear error if unconfigured."""
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is not set — cannot sign or "
            "verify tokens. Set it in .env (see .env.example)."
        )
    return secret


def _expire_minutes() -> int:
    raw = os.environ.get("JWT_EXPIRE_MINUTES")
    if not raw:
        return DEFAULT_EXPIRE_MINUTES
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_EXPIRE_MINUTES


def create_access_token(subject: str = "frontend", expires_minutes: int | None = None) -> str:
    """Issue a signed HS256 token for ``subject`` with an ``exp`` claim.

    expires_minutes defaults to JWT_EXPIRE_MINUTES. Pass STATIC_TOKEN_MINUTES
    (used by generate_token.py) to mint the long-lived token handed to the FE.
    """
    minutes = expires_minutes if expires_minutes is not None else _expire_minutes()
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """FastAPI dependency: validate the bearer token and return its subject.

    Raises 401 (with a ``WWW-Authenticate: Bearer`` header) for any
    missing/expired/invalid token.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise credentials_exc
    try:
        payload = jwt.decode(credentials.credentials, _secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise credentials_exc
    username = payload.get("sub")
    if not username:
        raise credentials_exc
    return username
