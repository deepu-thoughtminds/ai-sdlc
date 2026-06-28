"""SQLAlchemy ORM model and Pydantic schemas for the SDLC stage-transaction log.

ORM model (StageTransaction):
  Append-only timeline of human-readable events/results for a Jira ticket as it
  moves through the SDLC pipeline (describe → architecture → dev → merge → qa →
  deploy). Multiple rows per (project_id, ticket_key) — never updated in place.

  Unlike pipeline_states (machine status per run, used for idempotency guards),
  this table stores a friendly message and an optional result URL (Confluence
  page, GitHub PR) so the status/detail APIs can render a readable history.

Pydantic schemas:
  StageTransactionCreate — inbound payload (for a future manual record endpoint)
  StageTransactionPublic — outbound payload; all fields are non-sensitive

Threat mitigations:
  result_url / detail must never contain credential values — callers interpolate
  only URLs and identifiers, mirroring the existing pipeline comment conventions.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import Doc
from models.ticket_status import VALID_STAGES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRANSACTION_STATUSES: frozenset = frozenset({"success", "failed", "in_progress"})


# ---------------------------------------------------------------------------
# Document type
# ---------------------------------------------------------------------------

# Append-only documents in the `stage_transactions` collection. Insert/read
# logic lives in repositories/stage_transaction_repo.py. `StageTransaction` is a
# Doc alias kept for type-hint compatibility.
# Fields: id, project_id, ticket_key, stage, event, status, result_url, detail,
# created_at.
StageTransaction = Doc


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class StageTransactionCreate(BaseModel):
    """Inbound schema for creating a stage transaction (future manual endpoint).

    Validates stage against the shared VALID_STAGES and status against
    TRANSACTION_STATUSES so bad values are rejected with 422.
    """

    ticket_key: str = Field(..., min_length=1, max_length=100)
    stage: str = Field(..., min_length=1)
    event: str = Field(..., min_length=1, max_length=500)
    status: str = "success"
    result_url: str | None = Field(default=None, max_length=2000)
    detail: str | None = None

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, v: str) -> str:
        if v not in VALID_STAGES:
            raise ValueError(f"stage must be one of {sorted(VALID_STAGES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in TRANSACTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(TRANSACTION_STATUSES)}")
        return v


class StageTransactionPublic(BaseModel):
    """Outbound schema for a single stage transaction — no sensitive fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_key: str
    stage: str
    event: str
    status: str
    result_url: str | None
    detail: str | None
    created_at: datetime
