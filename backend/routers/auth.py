"""Authentication endpoint.

There is no login endpoint — the frontend is given a long-lived static JWT
(generated via backend/generate_token.py, stored in env as API_TOKEN) and sends
it as ``Authorization: Bearer <token>`` on every request. This module only
exposes a probe so the FE can confirm its token is valid.

  GET /api/auth/me — protected; echoes back the token subject.
"""

from fastapi import APIRouter, Depends

from services.auth import get_current_user

router = APIRouter()


@router.get("/auth/me")
def read_me(subject: str = Depends(get_current_user)) -> dict:
    """Return the token's subject — a quick token-validity check for the FE."""
    return {"subject": subject}
