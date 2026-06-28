"""One-time SQLite -> MongoDB data migration.

Copies every row from the legacy SQLite database (app.db) into the matching
MongoDB collection, preserving the integer primary key as Mongo `_id` and
copying Fernet-encrypted credential fields verbatim (no re-encryption). After
copying, seeds the `counters` collection to max(id) per collection so new
inserts from the app never collide with migrated ids.

Run ONCE, after MongoDB is up and before (or just after) starting the new
backend. Safe to re-run only against an empty target — it uses insert and will
raise DuplicateKeyError if a document already exists.

Usage (from the host, with the local compose Mongo published on 27017):

    cd backend
    SQLITE_DB_PATH=../app.db \
    MONGODB_URI="mongodb://localhost:27017/?replicaSet=rs0" \
    MONGODB_DB=aisdlc \
    python scripts/migrate_sqlite_to_mongo.py

Or inside the backend container (point SQLITE_DB_PATH at the old volume file):

    docker compose exec backend python scripts/migrate_sqlite_to_mongo.py /app/data/app.db

Environment:
    SQLITE_DB_PATH  path to app.db (or pass as the first CLI argument)
    MONGODB_URI     defaults to mongodb://localhost:27017/?replicaSet=rs0
    MONGODB_DB      defaults to aisdlc
"""

import os
import sqlite3
import sys
from datetime import datetime

from pymongo import MongoClient

# Collection -> ordered column list. Mirrors the old SQLAlchemy models.
TABLES: dict[str, list[str]] = {
    "projects": [
        "id", "name", "project_key", "jira_url", "jira_email", "confluence_url",
        "github_url", "jira_token", "github_token", "confluence_token",
        "github_repo", "created_at",
    ],
    "ticket_statuses": [
        "id", "project_id", "ticket_key", "pipeline_stage", "summary",
        "issue_type", "current_status", "created_at", "updated_at",
    ],
    "stage_transactions": [
        "id", "project_id", "ticket_key", "stage", "event", "status",
        "result_url", "detail", "created_at",
    ],
    "pipeline_states": [
        "id", "project_id", "ticket_key", "stage", "status", "draft_content",
        "complexity", "complexity_rationale", "qa_attempt", "created_at",
        "updated_at",
    ],
}

# Columns whose SQLite text value should be parsed into a datetime.
_DATETIME_COLUMNS = {"created_at", "updated_at"}


def _coerce(column: str, value):
    """Parse datetime columns from SQLite text into datetime; pass others through."""
    if value is None or column not in _DATETIME_COLUMNS:
        return value
    if isinstance(value, datetime):
        return value
    try:
        # SQLAlchemy stores DateTime as 'YYYY-MM-DD HH:MM:SS[.ffffff]'.
        return datetime.fromisoformat(str(value))
    except ValueError:
        return value  # leave as-is rather than lose data


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def main() -> None:
    sqlite_path = (
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SQLITE_DB_PATH", "app.db")
    )
    mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/?replicaSet=rs0")
    mongo_db_name = os.environ.get("MONGODB_DB", "aisdlc")

    if not os.path.exists(sqlite_path):
        sys.exit(f"SQLite database not found: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    mongo = MongoClient(mongo_uri)
    db = mongo[mongo_db_name]

    print(f"Migrating {sqlite_path} -> {mongo_uri} / {mongo_db_name}\n")

    existing_tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    for coll, columns in TABLES.items():
        if coll not in existing_tables:
            print(f"  {coll:<20} (no such SQLite table — skipped)")
            continue

        present = _table_columns(conn, coll)
        cols = [c for c in columns if c in present]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM {coll}").fetchall()

        docs = []
        max_id = 0
        for row in rows:
            doc = {}
            for col in cols:
                value = _coerce(col, row[col])
                if col == "id":
                    doc["_id"] = value
                    if isinstance(value, int):
                        max_id = max(max_id, value)
                else:
                    doc[col] = value
            docs.append(doc)

        if docs:
            db[coll].insert_many(docs)
        # Seed the counter so the next app insert continues past the migrated max.
        db["counters"].update_one(
            {"_id": coll}, {"$set": {"seq": max_id}}, upsert=True
        )
        print(f"  {coll:<20} {len(docs):>5} rows migrated (counter seeded to {max_id})")

    conn.close()
    mongo.close()
    print("\nDone. Verify counts against the SQLite source before deleting app.db.")


if __name__ == "__main__":
    main()
