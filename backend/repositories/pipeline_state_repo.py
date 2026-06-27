"""Repository for the `pipeline_states` collection.

Machine state per pipeline run, used by the webhook idempotency guards and the
pipeline services (architecture/dev/merge/qa). Multiple rows per
(project_id, ticket_key, stage) are allowed — each is a separate run.

Translation of the old SQLAlchemy patterns:
  db.query(PipelineState).filter(...).order_by(...).first()  -> find_latest(...)
  state_row.x = y; db.commit()                               -> update(state_id, x=y)
  db.query(...).filter(...).update({...})                    -> update_status_many(...)
"""

from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.database import Database

from database import Doc, next_id, to_doc

COLL = "pipeline_states"


def create(
    db: Database,
    project_id: int,
    ticket_key: str,
    stage: str,
    *,
    status: str = "pending",
    draft_content: str | None = None,
    complexity: str | None = None,
    complexity_rationale: str | None = None,
    qa_attempt: int | None = None,
) -> Doc:
    """Insert a new pipeline-state row and return it."""
    now = datetime.now(timezone.utc)
    doc = {
        "_id": next_id(db, COLL),
        "project_id": project_id,
        "ticket_key": ticket_key,
        "stage": stage,
        "status": status,
        "draft_content": draft_content,
        "complexity": complexity,
        "complexity_rationale": complexity_rationale,
        "qa_attempt": qa_attempt,
        "created_at": now,
        "updated_at": now,
    }
    db[COLL].insert_one(doc)
    return to_doc(doc)


def get(db: Database, state_id: int) -> Doc | None:
    """Return a pipeline-state row by id, or None."""
    return to_doc(db[COLL].find_one({"_id": state_id}))


def find_latest(
    db: Database,
    *,
    ticket_key: str | None = None,
    stage: str | None = None,
    statuses: list[str] | None = None,
    project_id: int | None = None,
    order_field: str = "created_at",
) -> Doc | None:
    """Return the most recent matching row (or None).

    statuses, when given, matches any of the listed status values ($in).
    order_field selects the sort key ("created_at" or "_id"); ties break on _id.
    """
    query: dict = {}
    if ticket_key is not None:
        query["ticket_key"] = ticket_key
    if stage is not None:
        query["stage"] = stage
    if project_id is not None:
        query["project_id"] = project_id
    if statuses is not None:
        query["status"] = {"$in": list(statuses)}

    cursor = db[COLL].find(query).sort([(order_field, -1), ("_id", -1)]).limit(1)
    docs = list(cursor)
    return to_doc(docs[0]) if docs else None


def update(db: Database, state_id: int, **fields) -> Doc | None:
    """Apply a $set update (always bumping updated_at) and return the row."""
    fields["updated_at"] = datetime.now(timezone.utc)
    return to_doc(
        db[COLL].find_one_and_update(
            {"_id": state_id},
            {"$set": fields},
            return_document=ReturnDocument.AFTER,
        )
    )


def update_status_many(db: Database, query: dict, to_status: str) -> int:
    """Bulk-update status for all rows matching `query`. Returns modified count.

    Used for superseding stale awaiting_approval states and for marking an
    in-flight scan as errored.
    """
    res = db[COLL].update_many(
        query,
        {"$set": {"status": to_status, "updated_at": datetime.now(timezone.utc)}},
    )
    return res.modified_count


def delete_for_project(db: Database, project_id: int) -> int:
    """Delete all pipeline-state rows for a project. Returns the deleted count."""
    return db[COLL].delete_many({"project_id": project_id}).deleted_count
