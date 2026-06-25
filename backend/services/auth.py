"""JWT authentication core: token issuance, credential check, and the
``get_current_user`` FastAPI dependency used to protect ``/api`` routes.

Design:
  - Stateless HS256 access tokens signed with ``JWT_SECRET_KEY``. A token carries
    ``sub`` (the username) and ``exp`` (expiry). No server-side session store.
  - Credentials are validated against a single admin seeded from env vars
    (``AUTH_ADMIN_USERNAME`` / ``AUTH_ADMIN_PASSWORD``). A real users table can be
    added later by swapping the lookup in ``verify_credentials`` — the token logic
    and the ``get_current_user`` dependency stay unchanged.

Env vars (read lazily inside functions so tests can set them before import,
mirroring services/crypto.py):
  JWT_SECRET_KEY       required — HMAC signing secret; functions raise if unset.
  JWT_EXPIRE_MINUTES   optional — access token lifetime in minutes (default 720).
  AUTH_ADMIN_USERNAME  required for login — the single admin username.
  AUTH_ADMIN_PASSWORD  required for login — the single admin password.

Security notes:
  - The signing secret and admin password are never logged.
  - Username/password comparison uses hmac.compare_digest (constant-time) to avoid
    leaking validity via timing.
"""

import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 720  # 12 hours

# HTTPBearer (not OAuth2PasswordBearer) so Swagger's Authorize dialog shows a
# single "paste your token" box that pairs with our JSON login endpoint.
# auto_error=False lets us return 401 (not HTTPBearer's default 403) for a
# missing/malformed Authorization header.
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


def create_access_token(username: str) -> str:
    """Issue a signed HS256 access token for ``username`` with an ``exp`` claim."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(minutes=_expire_minutes()),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def verify_credentials(username: str, password: str) -> bool:
    """Constant-time check of ``username``/``password`` against the env admin.

    Returns False (deny) if the admin env vars are not configured, so a
    misconfigured deployment never accidentally authenticates anyone.
    """
    expected_user = os.environ.get("AUTH_ADMIN_USERNAME", "")
    expected_pass = os.environ.get("AUTH_ADMIN_PASSWORD", "")
    if not expected_user or not expected_pass:
        return False
    # Evaluate both comparisons (no short-circuit) to keep timing uniform.
    user_ok = hmac.compare_digest(username, expected_user)
    pass_ok = hmac.compare_digest(password, expected_pass)
    return user_ok and pass_ok


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """FastAPI dependency: validate the bearer token and return its username.

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
