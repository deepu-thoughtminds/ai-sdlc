"""Pydantic v2 models for Jira comment webhook payload.

Matches the Jira Cloud webhook schema for "comment_created" and
"comment_updated" events. For the Walking Skeleton, author is treated as a
plain string (display name). Full ADF and nested-author parsing ships in
Phase 3.

Threat mitigations applied:
- T-02-04: comment.body has max_length=10000 to prevent DoS via oversized payloads.
"""

from pydantic import BaseModel, ConfigDict, Field


class JiraComment(BaseModel):
    """Represents a single Jira comment."""

    id: str
    body: str = Field(..., max_length=10000)  # T-02-04: bound body size
    author_display_name: str = Field(default="", alias="author")
    created: str = ""
    updated: str = ""

    model_config = ConfigDict(populate_by_name=True)


class JiraIssue(BaseModel):
    """Minimal Jira issue fields included in the webhook payload."""

    id: str
    key: str  # e.g. "PROJ-123"
    summary: str = ""


class JiraCommentEvent(BaseModel):
    """Top-level webhook event sent by Jira Cloud on comment_created / comment_updated."""

    webhook_event: str  # "comment_created" | "comment_updated"
    issue: JiraIssue
    comment: JiraComment
    timestamp: int = 0
