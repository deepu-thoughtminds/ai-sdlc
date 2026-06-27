"""Repository for the `ticket_statuses` collection.

One document per (project_id, ticket_key) — enforced by a unique compound index.
upsert() ports services/ticket_tracking.upsert_ticket_status and the dashboard
upsert into a single atomic find_one_and_update, setting created_at/updated_at
in app code (Mongo has no server_default / onupdate).
"""

from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.database import Database

from database import Doc, next_id, to_doc
from models.ticket_status import VALID_STAGES

COLL = "ticket_statuses"


def get(db: Database, project_id: int, ticket_key: str) -> Doc | None:
    """Return the status row for (project_id, ticket_key), or None."""
    return to_doc(db[COLL].find_one({"project_id": project_id, "ticket_key": ticket_key}))


def list_for_project(db: Database, project_id: int) -> list[Doc]:
    """Return all status rows for a project, newest-updated first."""
    return [to_doc(d) for d in db[COLL].find({"project_id": project_id}).sort("updated_at", -1)]


def upsert(
    db: Database,
    project_id: int,
    ticket_key: str,
    *,
    pipeline_stage: str | None = None,
    current_status: str | None = None,
    summary: str | None = None,
    issue_type: str | None = None,
) -> Doc:
    """Create or update the single status row for (project_id, ticket_key).

    Only non-None fields are written, so callers can update current_status
    without clobbering a previously stored summary. A brand-new row defaults
    pipeline_stage to "description" (the old NOT NULL coarse stage default).
    """
    if pipeline_stage is not None and pipeline_stage not in VALID_STAGES:
        raise ValueError(
            f"pipeline_stage must be one of {sorted(VALID_STAGES)}, got {pipeline_stage!r}"
        )

    now = datetime.now(timezone.utc)
    set_fields: dict = {"updated_at": now}
    for key, value in (
        ("pipeline_stage", pipeline_stage),
        ("current_status", current_status),
        ("summary", summary),
        ("issue_type", issue_type),
    ):
        if value is not None:
            set_fields[key] = value

    set_on_insert: dict = {
        "_id": next_id(db, COLL),
        "project_id": project_id,
        "ticket_key": ticket_key,
        "created_at": now,
    }
    # Only default pipeline_stage on insert when the caller did not supply one
    # (avoids a conflicting field between $set and $setOnInsert).
    if "pipeline_stage" not in set_fields:
        set_on_insert["pipeline_stage"] = "description"

    return to_doc(
        db[COLL].find_one_and_update(
            {"project_id": project_id, "ticket_key": ticket_key},
            {"$set": set_fields, "$setOnInsert": set_on_insert},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    )


def delete_for_project(db: Database, project_id: int) -> int:
    """Delete all status rows for a project. Returns the deleted count."""
    return db[COLL].delete_many({"project_id": project_id}).deleted_count
