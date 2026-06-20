"""SQLAlchemy ORM model and Pydantic schemas for projects.

ORM model (Project):
  Stores project metadata and Fernet-encrypted credentials.
  Token fields (jira_token, github_token, confluence_token) are stored as
  Fernet ciphertext — never plaintext. See services/crypto.py encrypt/decrypt.
  github_repo is also stored as Fernet ciphertext (GITHUBCFG-01).

Pydantic schemas:
  ProjectCreate — inbound payload; accepts plaintext tokens for encryption
  ProjectPublic — outbound payload; OMITS all token fields (T-02-02 mitigation)
                  but INCLUDES decrypted github_repo (GITHUBCFG-02)
  ProjectListItem — compact list payload; no URL or token fields

Threat mitigations:
  T-02-01: ProjectCreate enforces max_length on all string fields; HttpUrl on URL fields
  T-02-02: ProjectPublic/ProjectListItem never expose token fields
  T-02-05: project_key pattern constraint prevents injection / path traversal
  T-02-06: max_length=500 on tokens; max_length=200 on name; max_length=50 on project_key
  T-15-01: github_repo pattern constrains to owner/repo slug shape; prevents injection
  T-15-02: github_repo stored as Fernet ciphertext; decrypted only at response time
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Project(Base):
    """ORM model for project records.

    Token columns store Fernet-encrypted base64 ciphertext, not plaintext.
    github_repo also stored as Fernet ciphertext — see services/crypto.py.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    jira_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    jira_email: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    confluence_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Optional GitHub repository URL for codebase context (graphify_service)
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Encrypted credentials (Fernet ciphertext — see services/crypto.py)
    jira_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    github_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    confluence_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Stored as Fernet ciphertext — see services/crypto.py. Owner/repo slug, e.g. "acme/my-app".
    github_repo: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    ticket_statuses: Mapped[list["TicketStatus"]] = relationship(  # type: ignore[name-defined]
        "TicketStatus", back_populates="project", cascade="all, delete-orphan"
    )


class ProjectCreate(BaseModel):
    """Inbound schema for creating a new project.

    All string fields are bounded (Threat T-02-01).
    Threat T-02-01: HttpUrl on URL fields; max_length prevents DoS via oversized payloads.
    Threat T-02-05: project_key ^[A-Z0-9_-]+$ (no injection).
    Threat T-02-06: bounded lengths prevent DoS via oversized payloads.
    Threat T-15-01: github_repo pattern constrains to owner/repo slug shape.
    """

    name: str = Field(..., min_length=1, max_length=200)
    project_key: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z0-9_-]+$",
    )
    jira_url: HttpUrl
    jira_email: str = Field(default="", max_length=500)
    confluence_url: HttpUrl
    jira_token: str = Field(..., min_length=1, max_length=500)
    github_token: str = Field(..., min_length=1, max_length=500)
    confluence_token: str = Field(..., min_length=1, max_length=500)
    # Owner/repo slug (e.g. "acme/my-app") — stored encrypted per GITHUBCFG-01
    github_repo: str = Field(..., min_length=1, max_length=500, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProjectPublic(BaseModel):
    """Outbound schema for a single project — NO token fields.

    Threat T-02-02: token fields deliberately excluded from schema.
    Never add jira_token, github_token, confluence_token here.
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


class ProjectListItem(BaseModel):
    """Compact outbound schema for project list view — NO token fields, NO URLs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_key: str
    created_at: datetime
