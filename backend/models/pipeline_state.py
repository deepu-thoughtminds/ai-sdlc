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

from database import Doc

# Documents in the `pipeline_states` collection — machine state per pipeline run.
# Multiple documents per (project_id, ticket_key, stage) are permitted (one per
# run). CRUD/idempotency queries live in repositories/pipeline_state_repo.py.
# `PipelineState` is a Doc alias kept for type-hint compatibility.
# Fields: id, project_id, ticket_key, stage, status, draft_content, complexity,
# complexity_rationale, qa_attempt, created_at, updated_at.
# (complexity is one of 'small'|'complex'|None — formerly a CHECK constraint;
# now enforced by complexity_classifier returning only those values.)
PipelineState = Doc


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
    qa_attempt: int | None = None


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
    qa_attempt: int | None
    created_at: datetime
    updated_at: datetime
