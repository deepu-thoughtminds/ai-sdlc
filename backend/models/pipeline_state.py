"""SQLAlchemy ORM model and Pydantic schemas for pipeline execution state.

ORM model (PipelineState):
  Tracks the state of a pipeline stage execution for a given ticket.
  Multiple rows allowed per (project_id, ticket_key, stage) — each represents
  a separate pipeline run (e.g., re-triggering the describe stage after edits).

Pydantic schemas:
  PipelineStateCreate  — inbound payload for creating a new pipeline state record
  PipelineStatePublic  — outbound payload with all non-sensitive fields

Status lifecycle:
  pending → processing → awaiting_approval → approved
                      └→ failed

Threat mitigations:
  T-03-07: draft_content stored in local SQLite; not returned in any API response
           in this plan; access controlled by same DB layer as project tokens
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PipelineState(Base):
    """ORM model for pipeline stage execution state.

    Multiple rows per (project_id, ticket_key, stage) are permitted to track
    separate pipeline runs. No unique constraint is imposed.
    """

    __tablename__ = "pipeline_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    ticket_key: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    # status values: pending | processing | awaiting_approval | approved | failed
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    draft_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added Phase 10 — requires DB recreation (docker compose down -v) upgrading prior schema
    complexity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    complexity_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PipelineStateCreate(BaseModel):
    """Inbound schema for creating a pipeline state record."""

    project_id: int
    ticket_key: str
    stage: str
    status: str = "pending"
    draft_content: str | None = None
    complexity: str | None = None
    complexity_rationale: str | None = None


class PipelineStatePublic(BaseModel):
    """Outbound schema for a pipeline state record.

    Threat T-03-07: draft_content is included here for completeness but the
    router layer controls access — only internal callers see this schema in
    this plan.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    ticket_key: str
    stage: str
    status: str
    draft_content: str | None
    complexity: str | None
    complexity_rationale: str | None
    created_at: datetime
    updated_at: datetime
