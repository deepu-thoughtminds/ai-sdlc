"""Tests for the agent_events collection, schemas, helpers and read endpoint.

Uses the shared mongomock fixtures in conftest.py.
"""

from datetime import datetime

import pytest

from models.agent_event import AgentEventCreate, AgentEventPublic
from repositories import agent_event_repo, ticket_status_repo
from services.ticket_tracking import record_agent_event
from tests.support import make_project


def test_agent_event_create_and_read(db) -> None:
    p = make_project(db)
    ev = agent_event_repo.append(
        db, p.id, "P-1", "dev", "action", "Write", tool_name="Write",
        detail="backend/main.py",
    )
    assert isinstance(ev.id, int)
    assert isinstance(ev.created_at, datetime)
    assert ev.event_type == "action"
    assert ev.tool_name == "Write"
    assert ev.detail == "backend/main.py"


def test_events_ordered_oldest_first(db) -> None:
    p = make_project(db)
    for etype, content in [
        ("thinking", "Reading the codebase"),
        ("action", "Read"),
        ("goal", "PR ready"),
    ]:
        agent_event_repo.append(db, p.id, "P-1", "dev", etype, content)

    rows = agent_event_repo.list_for_ticket(db, p.id, "P-1")
    assert [r.event_type for r in rows] == ["thinking", "action", "goal"]


def test_public_schema_round_trip(db) -> None:
    p = make_project(db)
    ev = agent_event_repo.append(db, p.id, "P-1", "architecture", "decision", "Classified as complex")
    pub = AgentEventPublic.model_validate(ev)
    assert pub.event_type == "decision"
    assert pub.content == "Classified as complex"
    # project_id is internal and not exposed in the public schema
    assert not hasattr(pub, "project_id")


def test_create_schema_rejects_invalid_event_type() -> None:
    with pytest.raises(ValueError):
        AgentEventCreate(ticket_key="P-1", stage="dev", event_type="bogus", content="x")


def test_record_agent_event_rejects_invalid_stage(db) -> None:
    p = make_project(db)
    with pytest.raises(ValueError):
        record_agent_event(db, p.id, "P-1", "bogus", "thinking", "x")


def test_agent_events_endpoint_returns_log(client, db) -> None:
    p = make_project(db)
    ticket_status_repo.upsert(db, p.id, "P-1", pipeline_stage="dev")
    agent_event_repo.append(db, p.id, "P-1", "dev", "thinking", "Planning the change")
    agent_event_repo.append(db, p.id, "P-1", "dev", "goal", "PR ready", detail="https://github.com/acme/x/pull/3")

    res = client.get(f"/api/projects/{p.id}/tickets/P-1/agent-events")
    assert res.status_code == 200
    body = res.json()
    assert [e["event_type"] for e in body] == ["thinking", "goal"]
    assert body[1]["detail"].endswith("/pull/3")


def test_agent_events_endpoint_404_for_unknown_ticket(client, db) -> None:
    p = make_project(db)
    res = client.get(f"/api/projects/{p.id}/tickets/NOPE-1/agent-events")
    assert res.status_code == 404
