"""Repository for the `projects` collection.

Ports the inline SQLAlchemy CRUD from routers/projects.py. project_key
uniqueness is enforced by a unique index (see database.init_indexes) — callers
catch pymongo.errors.DuplicateKeyError and map it to HTTP 409.

Credential fields (jira_token, github_token, confluence_token, github_repo) are
stored as Fernet ciphertext exactly as before — this layer never encrypts or
decrypts; it stores whatever strings it is given.
"""

from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.database import Database

from database import Doc, next_id, to_doc
from repositories import pipeline_state_repo, stage_transaction_repo, ticket_status_repo

COLL = "projects"


def create(
    db: Database,
    *,
    name: str,
    project_key: str,
    jira_url: str,
    jira_email: str,
    confluence_url: str,
    github_url: str | None,
    jira_token: str,
    github_token: str,
    confluence_token: str,
    github_repo: str,
) -> Doc:
    """Insert a new project and return it. Raises DuplicateKeyError on key clash."""
    doc = {
        "_id": next_id(db, COLL),
        "name": name,
        "project_key": project_key,
        "jira_url": jira_url,
        "jira_email": jira_email,
        "confluence_url": confluence_url,
        "github_url": github_url,
        "jira_token": jira_token,
        "github_token": github_token,
        "confluence_token": confluence_token,
        "github_repo": github_repo,
        "created_at": datetime.now(timezone.utc),
    }
    db[COLL].insert_one(doc)
    return to_doc(doc)


def get(db: Database, project_id: int) -> Doc | None:
    """Return the project by id, or None."""
    return to_doc(db[COLL].find_one({"_id": project_id}))


def get_by_key(db: Database, project_key: str) -> Doc | None:
    """Return the project by project_key, or None."""
    return to_doc(db[COLL].find_one({"project_key": project_key}))


def list_all(db: Database) -> list[Doc]:
    """Return all projects (insertion order by id)."""
    return [to_doc(d) for d in db[COLL].find().sort("_id", 1)]


def update(db: Database, project_id: int, **fields) -> Doc | None:
    """Apply a partial $set update and return the updated project (or None).

    Raises DuplicateKeyError if a new project_key collides with another project.
    """
    if not fields:
        return get(db, project_id)
    return to_doc(
        db[COLL].find_one_and_update(
            {"_id": project_id},
            {"$set": fields},
            return_document=ReturnDocument.AFTER,
        )
    )


def delete(db: Database, project_id: int) -> bool:
    """Delete a project and all of its related rows. Returns True if it existed.

    Replaces the ORM cascade + explicit cleanup: SQLite cascades only covered
    ticket_statuses, with pipeline_states/stage_transactions deleted by hand.
    Here all three child collections are cleared explicitly.
    """
    ticket_status_repo.delete_for_project(db, project_id)
    pipeline_state_repo.delete_for_project(db, project_id)
    stage_transaction_repo.delete_for_project(db, project_id)
    return db[COLL].delete_one({"_id": project_id}).deleted_count > 0
