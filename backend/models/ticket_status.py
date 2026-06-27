"""SQLAlchemy ORM model and Pydantic schemas for ticket pipeline statuses.

ORM model (TicketStatus):
  Stores the current SDLC pipeline stage for a Jira ticket, linked to a project.
  Unique constraint on (project_id, ticket_key) ensures one status row per ticket per project.

Pydantic schemas:
  TicketStatusCreate  — inbound payload; validates pipeline_stage against VALID_STAGES
  TicketStatusPublic  — outbound payload; no sensitive fields
  ProjectWithTickets  — extends ProjectPublic with nested ticket_statuses list

Threat mitigations:
  T-02-09: @field_validator on TicketStatusCreate rejects any stage not in VALID_STAGES
  T-02-10: project_id FK enforced; dashboard router verifies project exists before upsert
  T-02-08: ProjectWithTickets schema never includes token fields from the Project join
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import Doc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STAGES: frozenset = frozenset(
    {"description", "architecture", "dev", "merge", "qa", "deploy", "done"}
)


# ---------------------------------------------------------------------------
# Document type
# ---------------------------------------------------------------------------

# One document per (project_id, ticket_key) in the `ticket_statuses` collection
# (uniqueness enforced by a compound index — see database.init_indexes). Upsert
# logic lives in repositories/ticket_status_repo.py. `TicketStatus` is a Doc
# alias kept for type-hint compatibility.
# Fields: id, project_id, ticket_key, pipeline_stage, summary, issue_type,
# current_status, created_at, updated_at.
TicketStatus = Doc


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TicketStatusCreate(BaseModel):
    """Inbound schema for creating/updating a ticket pipeline status.

    Threat T-02-09: @field_validator rejects any stage not in VALID_STAGES.
    """

    ticket_key: str = Field(..., min_length=1, max_length=100)
    pipeline_stage: str = Field(..., min_length=1)

    @field_validator("pipeline_stage")
    @classmethod
    def validate_pipeline_stage(cls, v: str) -> str:
        if v not in VALID_STAGES:
            raise ValueError(
                f"pipeline_stage must be one of {sorted(VALID_STAGES)}"
            )
        return v


class TicketStatusPublic(BaseModel):
    """Outbound schema for a single ticket status — no sensitive fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_key: str
    pipeline_stage: str
    summary: str | None = None
    issue_type: str | None = None
    current_status: str | None = None
    updated_at: datetime


class ProjectWithTickets(BaseModel):
    """Outbound schema for a project with its nested ticket statuses.

    Threat T-02-08: deliberately excludes all token fields from the Project join.
    Never add jira_token, github_token, or confluence_token here.
    github_repo is intentionally included (decrypted) per GITHUBCFG-02.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_key: str
    jira_url: str
    confluence_url: str
    github_repo: str
    created_at: datetime
    ticket_statuses: list[TicketStatusPublic]
