"""Document type and Pydantic schemas for captured agent activity.

Append-only log of what the AI agent *thought*, *did*, *decided*, and ultimately
*achieved* while moving a Jira ticket through the SDLC pipeline. Unlike
stage_transactions (coarse human-readable milestones with a result URL), this
collection records the fine-grained reasoning and tool-by-tool actions emitted
by the Claude Agent SDK loop (services/agentic_coder.py) plus decision and goal
markers from the pipelines, so the frontend can replay the agent's journey.

Event types (AGENT_EVENT_TYPES):
  thinking — a reasoning/text block from the agent
  action   — a tool invocation (Read/Write/Bash/Glob/Grep); tool_name is set
  decision — a branch the pipeline took (e.g. complexity classification)
  goal     — a final outcome (PR ready, QA passed, PR merged)

Pydantic schemas:
  AgentEventCreate — inbound payload (validated; future manual record endpoint)
  AgentEventPublic — outbound payload; all fields are non-sensitive

Threat mitigations:
  content / detail must never contain credential values — callers pass only
  reasoning text, tool names, file paths and identifiers, mirroring the existing
  stage-transaction conventions.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import Doc
from models.ticket_status import VALID_STAGES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_EVENT_TYPES: frozenset = frozenset({"thinking", "action", "decision", "goal"})


# ---------------------------------------------------------------------------
# Document type
# ---------------------------------------------------------------------------

# Append-only documents in the `agent_events` collection. Insert/read logic lives
# in repositories/agent_event_repo.py. `AgentEvent` is a Doc alias kept for
# type-hint compatibility.
# Fields: id, project_id, ticket_key, stage, event_type, content, tool_name,
# detail, created_at.
AgentEvent = Doc


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AgentEventCreate(BaseModel):
    """Inbound schema for creating an agent event (future manual endpoint).

    Validates stage against the shared VALID_STAGES and event_type against
    AGENT_EVENT_TYPES so bad values are rejected with 422.
    """

    ticket_key: str = Field(..., min_length=1, max_length=100)
    stage: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    tool_name: str | None = Field(default=None, max_length=100)
    detail: str | None = None

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, v: str) -> str:
        if v not in VALID_STAGES:
            raise ValueError(f"stage must be one of {sorted(VALID_STAGES)}")
        return v

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in AGENT_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(AGENT_EVENT_TYPES)}")
        return v


class AgentEventPublic(BaseModel):
    """Outbound schema for a single agent event — no sensitive fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_key: str
    stage: str
    event_type: str
    content: str
    tool_name: str | None
    detail: str | None
    created_at: datetime
