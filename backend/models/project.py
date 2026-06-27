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

from database import Doc

# Project documents are plain Mongo documents accessed via Doc (attribute-style
# dict). `Project` remains importable as a type alias so service/pipeline
# signatures (`project: Project`) read unchanged after the SQLite→Mongo move.
# Fields: id, name, project_key, jira_url, jira_email, confluence_url,
# github_url, jira_token, github_token, confluence_token, github_repo,
# created_at. The four credential fields store Fernet ciphertext (services/
# crypto.py) — never plaintext.
Project = Doc


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


class ProjectUpdate(BaseModel):
    """Inbound schema for updating an existing project (PUT /projects/{id}).

    All fields are optional — only provided fields are changed. Token and
    github_repo fields, when omitted or sent empty, leave the stored ciphertext
    unchanged; when provided non-empty they are re-encrypted by the router.

    Validation mirrors ProjectCreate so an update can never weaken the
    constraints enforced at creation (T-02-01/05/06, T-15-01).
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    project_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z0-9_-]+$",
    )
    jira_url: HttpUrl | None = None
    jira_email: str | None = Field(default=None, max_length=500)
    confluence_url: HttpUrl | None = None
    jira_token: str | None = Field(default=None, max_length=500)
    github_token: str | None = Field(default=None, max_length=500)
    confluence_token: str | None = Field(default=None, max_length=500)
    github_repo: str | None = Field(
        default=None,
        max_length=500,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


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
