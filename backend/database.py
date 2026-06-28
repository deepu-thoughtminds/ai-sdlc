"""MongoDB client, database handle, document helpers, and index bootstrap.

Provides:
- get_client():   process-wide MongoClient singleton (connection-pooled, thread-safe)
- get_database(): the application Database handle (name from MONGODB_DB)
- get_db():       FastAPI dependency generator yielding the Database
- Doc:            dict subclass with attribute access (`doc.id`, `doc.name`)
- to_doc():       map a raw Mongo document (`_id`) into a Doc (`id`)
- next_id():      monotonic integer id generator backed by a `counters` collection
- init_indexes(): create the unique/compound indexes (called at FastAPI startup)

Connection:
  Default: mongodb://mongo:27017/?replicaSet=rs0  (local single-node replica set)
  Override via MONGODB_URI. Database name via MONGODB_DB (default: aisdlc).

A single-node replica set is used (not a standalone) so multi-document
transactions are available and local topology matches a hosted Atlas cluster —
switching environments is a MONGODB_URI change only.

Integer ids: the public API contract uses integer ids (ProjectPublic.id: int,
path params like /projects/{project_id}: int) and the frontend depends on them,
so documents store the integer id as Mongo `_id` and new ids come from next_id()
(replacing SQLite AUTOINCREMENT). to_doc() surfaces `_id` back as `id`.
"""

import os
from collections.abc import Generator

from pymongo import MongoClient, ReturnDocument
from pymongo.database import Database

MONGODB_URI: str = os.environ.get("MONGODB_URI", "mongodb://mongo:27017/?replicaSet=rs0")
MONGODB_DB: str = os.environ.get("MONGODB_DB", "aisdlc")

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Return the process-wide MongoClient, creating it on first use.

    PyMongo's MongoClient is thread-safe and maintains its own connection pool,
    so the same instance is shared across requests and background tasks — there
    is no per-request/per-task session to open or close (unlike SQLAlchemy).
    """
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URI)
    return _client


def get_database() -> Database:
    """Return the application Database handle."""
    return get_client()[MONGODB_DB]


def get_db() -> Generator[Database, None, None]:
    """FastAPI dependency: yield the Database handle.

    Kept as a generator named get_db (mirroring the previous SQLAlchemy
    dependency) so route signatures only change in type, not in shape:

        @router.get("/items")
        def list_items(db: Database = Depends(get_db)):
            ...
    """
    yield get_database()


class Doc(dict):
    """A dict with attribute access — the universal repository return type.

    Lets call sites keep ORM-style attribute access (`project.id`,
    `project.jira_token`, `getattr(project, "jira_email", "")`) while the
    underlying value is a plain Mongo document. Because it is also a dict,
    Pydantic `model_validate(doc)` validates it as a mapping.
    """

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def to_doc(raw: dict | None) -> Doc | None:
    """Convert a raw Mongo document into a Doc, mapping `_id` → `id`.

    Returns None when raw is None so callers can do `to_doc(find_one(...))`.
    """
    if raw is None:
        return None
    doc = Doc(raw)
    if "_id" in doc:
        doc["id"] = doc.pop("_id")
    return doc


def next_id(db: Database, name: str) -> int:
    """Return the next monotonic integer id for the named sequence.

    Backed by a `counters` collection (one doc per collection name). Replaces
    SQLite's AUTOINCREMENT. The migration script seeds each counter to the max
    existing id so post-migration inserts never collide.
    """
    res = db["counters"].find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(res["seq"])


def init_indexes(db: Database) -> None:
    """Create all collection indexes. Called once at application startup.

    Idempotent — create_index is a no-op when the index already exists.

    Indexes mirror the old SQL constraints:
      projects.project_key                       UNIQUE  (was UniqueConstraint)
      ticket_statuses(project_id, ticket_key)    UNIQUE  (was uq_ticket_statuses_*)
      stage_transactions(project_id, ticket_key)         (was ix_stage_transactions_*)
      pipeline_states(project_id, ticket_key, stage)     (lookup index for guards)
      agent_events(project_id, ticket_key)               (per-ticket agent activity log)
    """
    db["projects"].create_index("project_key", unique=True, name="uq_projects_project_key")
    db["ticket_statuses"].create_index(
        [("project_id", 1), ("ticket_key", 1)],
        unique=True,
        name="uq_ticket_statuses_project_ticket",
    )
    db["stage_transactions"].create_index(
        [("project_id", 1), ("ticket_key", 1)],
        name="ix_stage_transactions_project_ticket",
    )
    db["pipeline_states"].create_index(
        [("project_id", 1), ("ticket_key", 1), ("stage", 1)],
        name="ix_pipeline_states_project_ticket_stage",
    )
    db["agent_events"].create_index(
        [("project_id", 1), ("ticket_key", 1)],
        name="ix_agent_events_project_ticket",
    )
