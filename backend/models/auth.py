"""Pydantic schemas for authentication endpoints.

LoginRequest  — inbound JSON body for POST /api/auth/login.
TokenResponse — outbound body carrying the signed access token.

Bounded lengths guard against oversized payloads (DoS), mirroring the field
constraints used on ProjectCreate in models/project.py.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Inbound credentials for the login endpoint."""

    username: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """Outbound access token. token_type is always 'bearer'."""

    access_token: str
    token_type: str = "bearer"
