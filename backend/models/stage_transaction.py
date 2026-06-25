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
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.ticket_status import VALID_STAGES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRANSACTION_STATUSES: frozenset = frozenset({"success", "failed", "in_progress"})


# ---------------------------------------------------------------------------
# ORM Model
# ---------------------------------------------------------------------------


class StageTransaction(Base):
    """ORM model for an append-only SDLC stage-transaction record."""

    __tablename__ = "stage_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    ticket_key: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    event: Mapped[str] = mapped_column(String(500), nullable=False)
    # status values: success | failed | in_progress
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    result_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_stage_transactions_project_ticket", "project_id", "ticket_key"),
    )


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
