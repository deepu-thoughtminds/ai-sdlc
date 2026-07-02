"""Repository for the `stage_transactions` collection.

Append-only SDLC timeline — one document per pipeline event, never updated in
place. Ports services/ticket_tracking.record_transaction and the read used by
routers/tickets.py.
"""

from datetime import datetime, timezone

from pymongo.database import Database

from database import Doc, next_id, to_doc

COLL = "stage_transactions"


def append(
    db: Database,
    project_id: int,
    ticket_key: str,
    stage: str,
    event: str,
    *,
    status: str = "success",
    result_url: str | None = None,
    detail: str | None = None,
) -> Doc:
    """Insert an immutable stage-transaction record and return it."""
    doc = {
        "_id": next_id(db, COLL),
        "project_id": project_id,
        "ticket_key": ticket_key,
        "stage": stage,
        "event": event,
        "status": status,
        "result_url": result_url,
        "detail": detail,
        "created_at": datetime.now(timezone.utc),
    }
    db[COLL].insert_one(doc)
    return to_doc(doc)


def list_for_ticket(db: Database, project_id: int, ticket_key: str) -> list[Doc]:
    """Return the full timeline for a ticket, oldest-first (created_at, then id)."""
    cursor = db[COLL].find({"project_id": project_id, "ticket_key": ticket_key}).sort(
        [("created_at", 1), ("_id", 1)]
    )
    return [to_doc(d) for d in cursor]


def delete_for_project(db: Database, project_id: int) -> int:
    """Delete all transactions for a project. Returns the deleted count."""
    return db[COLL].delete_many({"project_id": project_id}).deleted_count


def delete_for_ticket(db: Database, project_id: int, ticket_key: str) -> int:
    """Delete all transactions for (project_id, ticket_key). Returns the deleted count."""
    return db[COLL].delete_many(
        {"project_id": project_id, "ticket_key": ticket_key}
    ).deleted_count
