"""Repository for the `agent_events` collection.

Append-only log of captured agent activity (thinking / action / decision / goal)
for a ticket — one document per event, never updated in place. Mirrors
stage_transaction_repo: the pipelines append, routers/tickets.py reads.
"""

from datetime import datetime, timezone

from pymongo.database import Database

from database import Doc, next_id, to_doc

COLL = "agent_events"


def append(
    db: Database,
    project_id: int,
    ticket_key: str,
    stage: str,
    event_type: str,
    content: str,
    *,
    tool_name: str | None = None,
    detail: str | None = None,
) -> Doc:
    """Insert an immutable agent-event record and return it."""
    doc = {
        "_id": next_id(db, COLL),
        "project_id": project_id,
        "ticket_key": ticket_key,
        "stage": stage,
        "event_type": event_type,
        "content": content,
        "tool_name": tool_name,
        "detail": detail,
        "created_at": datetime.now(timezone.utc),
    }
    db[COLL].insert_one(doc)
    return to_doc(doc)


def list_for_ticket(db: Database, project_id: int, ticket_key: str) -> list[Doc]:
    """Return the full agent-event log for a ticket, oldest-first (created_at, then id)."""
    cursor = db[COLL].find({"project_id": project_id, "ticket_key": ticket_key}).sort(
        [("created_at", 1), ("_id", 1)]
    )
    return [to_doc(d) for d in cursor]


def delete_for_project(db: Database, project_id: int) -> int:
    """Delete all agent events for a project. Returns the deleted count."""
    return db[COLL].delete_many({"project_id": project_id}).deleted_count


def delete_for_ticket(db: Database, project_id: int, ticket_key: str) -> int:
    """Delete all agent events for (project_id, ticket_key). Returns the deleted count."""
    return db[COLL].delete_many(
        {"project_id": project_id, "ticket_key": ticket_key}
    ).deleted_count
