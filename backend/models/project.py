"""SQLAlchemy ORM model and Pydantic schemas for projects.

ORM model (Project):
  Stores project metadata and Fernet-encrypted credentials.
  Token fields (jira_token, github_token, confluence_token) are stored as
  Fernet ciphertext — never plaintext. See services/crypto.py for encrypt/decrypt.

Pydantic schemas:
  ProjectCreate  — inbound payload; accepts plaintext tokens for encryption
  ProjectPublic  — outbound payload; OMITS all token fields (T-02-02 mitigation)
  ProjectListItem — compact list payload; no URL or token fields

Threat mitigations:
  T-02-01: ProjectCreate enforces max_length on all string fields; HttpUrl on URL fields
  T-02-02: ProjectPublic/ProjectListItem never expose token fields
  T-02-05: project_key pattern constraint prevents injection / path traversal
  T-02-06: max_length=500 on tokens; max_length=200 on name; max_length=50 on project_key
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Project(Base):
    """ORM model for project records.

    Token columns store Fernet-encrypted base64 ciphertext, not plaintext.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    jira_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    confluence_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Stored as Fernet ciphertext — see services/crypto.py
    jira_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    github_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    confluence_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationship to TicketStatus (cascade delete when project is deleted)
    ticket_statuses: Mapped[list["TicketStatus"]] = relationship(  # type: ignore[name-defined]
        "TicketStatus", back_populates="project", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    """Inbound schema for creating a new project.

    Accepts plaintext tokens (they are encrypted before DB storage).
    Threat T-02-01: max_length enforced on all fields; HttpUrl on URL fields.
    Threat T-02-05: project_key must match ^[A-Z0-9_-]+$ (no injection).
    Threat T-02-06: bounded lengths prevent DoS via oversized payloads.
    """

    name: str = Field(..., min_length=1, max_length=200)
    project_key: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z0-9_-]+$",
    )
    jira_url: HttpUrl
    confluence_url: HttpUrl
    jira_token: str = Field(..., min_length=1, max_length=500)
    github_token: str = Field(..., min_length=1, max_length=500)
    confluence_token: str = Field(..., min_length=1, max_length=500)


class ProjectPublic(BaseModel):
    """Outbound schema for a single project — NO token fields.

    Threat T-02-02: token fields are deliberately excluded from this schema.
    Never add jira_token, github_token, or confluence_token here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_key: str
    jira_url: str
    confluence_url: str
    created_at: datetime


class ProjectListItem(BaseModel):
    """Compact outbound schema for project list view — NO token fields, NO URLs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_key: str
    created_at: datetime
