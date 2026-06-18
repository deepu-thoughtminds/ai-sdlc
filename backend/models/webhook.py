"""Pydantic v2 models for Jira comment webhook payload.

Matches the Jira Cloud webhook schema for "comment_created" and
"comment_updated" events. For the Walking Skeleton, author is treated as a
plain string (display name). Full ADF and nested-author parsing ships in
Phase 3.

Accepts real Jira Cloud webhook / Jira Automation "Send web request" payloads
(top-level webhookEvent, issue.fields.summary/description nested, comment.author
as an object) alongside the existing internal/test simplified shape
(webhook_event, flat issue.summary, comment.author as a plain string). No ADF
body parsing is performed — an ADF description object is coerced to "" rather
than rendered to text (still deferred, as in the original docstring note).

Threat mitigations applied:
- T-02-04: comment.body has max_length=10000 to prevent DoS via oversized payloads.
- T-Q260618-01: JiraIssue fields-flattening validator only reads via .get()
  with safe defaults; never executes/evals payload content; ADF dicts are
  coerced to empty string, not parsed/rendered.
- T-Q260618-03: comment.author object extraction only pulls displayName;
  accountId is dropped/ignored.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JiraComment(BaseModel):
    """Represents a single Jira comment."""

    id: str
    body: str = Field(..., max_length=10000)  # T-02-04: bound body size
    author_display_name: str = Field(default="", alias="author")
    created: str = ""
    updated: str = ""

    model_config = ConfigDict(populate_by_name=True)

    # Accepts real Jira Cloud webhookEvent + fields-nested + author-object shapes
    # alongside internal simplified shape: real Jira sends author as an object
    # ({"accountId": ..., "displayName": ...}); internal/test payloads send a
    # plain string. T-Q260618-03: only displayName is extracted, accountId dropped.
    @field_validator("author_display_name", mode="before")
    @classmethod
    def _coerce_author(cls, value):
        if isinstance(value, dict):
            return value.get("displayName", "")
        return value


class JiraIssue(BaseModel):
    """Minimal Jira issue fields included in the webhook payload."""

    id: str
    key: str  # e.g. "PROJ-123"
    summary: str = ""
    description: str = ""

    # Accepts real Jira Cloud webhookEvent + fields-nested + author-object shapes
    # alongside internal simplified shape: real Jira nests summary/description
    # under a "fields" object; internal/test payloads provide them flat.
    # T-Q260618-01: only reads via .get() with safe defaults, never executes
    # payload content; ADF description dicts are coerced to "" (no ADF parsing).
    @model_validator(mode="before")
    @classmethod
    def _flatten_fields(cls, data):
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            data = dict(data)  # shallow copy — avoid mutating caller's dict
            fields = data["fields"]
            data.setdefault("summary", fields.get("summary") or "")
            data.setdefault("description", fields.get("description") or "")
        if isinstance(data, dict) and isinstance(data.get("description"), dict):
            # ADF object slipped through — explicit deferral, no ADF parsing.
            data = dict(data)
            data["description"] = ""
        return data


class JiraCommentEvent(BaseModel):
    """Top-level webhook event sent by Jira Cloud on comment_created / comment_updated."""

    # Accepts both webhook_event (internal/test, snake_case) and webhookEvent
    # (real Jira Cloud, camelCase) via populate_by_name + alias.
    webhook_event: str = Field(..., alias="webhookEvent")  # "comment_created" | "comment_updated"
    issue: JiraIssue
    comment: JiraComment
    timestamp: int = 0

    model_config = ConfigDict(populate_by_name=True)
