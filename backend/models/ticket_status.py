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
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STAGES: frozenset = frozenset({"description", "architecture", "dev", "qa", "done"})


# ---------------------------------------------------------------------------
# ORM Model
# ---------------------------------------------------------------------------


class TicketStatus(Base):
    """ORM model for ticket pipeline status records.

    One row per (project_id, ticket_key) pair — upsert logic in dashboard router.
    """

    __tablename__ = "ticket_statuses"

    __table_args__ = (
        UniqueConstraint("project_id", "ticket_key", name="uq_ticket_statuses_project_ticket"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    ticket_key: Mapped[str] = mapped_column(String(100), nullable=False)
    pipeline_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationship back to Project (must match Project.ticket_statuses)
    project: Mapped["Project"] = relationship("Project", back_populates="ticket_statuses")  # type: ignore[name-defined]


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
