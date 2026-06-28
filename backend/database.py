"""SQLAlchemy database engine, session factory, and base model.

Provides:
- engine: SQLAlchemy engine backed by SQLite (path from DATABASE_URL env var)
- SessionLocal: sessionmaker factory for creating DB sessions
- Base: DeclarativeBase subclass — all ORM models inherit from this
- init_db(): creates all tables (called at FastAPI startup)
- get_db(): FastAPI dependency generator yielding a DB session

Database path:
  Default: sqlite:////app/data/app.db (Docker volume at /app/data)
  Override via DATABASE_URL env var (e.g. sqlite:///./local.db for local dev,
  or sqlite:///:memory: for tests)
"""

import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:////app/data/app.db")

# check_same_thread=False is required for SQLite when used with FastAPI because
# FastAPI handles requests across multiple threads.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def init_db() -> None:
    """Create all tables defined on Base.metadata.

    Called once at application startup (in main.py startup_event).
    Safe to call multiple times — SQLAlchemy uses CREATE TABLE IF NOT EXISTS.

    IMPORTANT — this does not add columns to existing tables:
    Base.metadata.create_all() only issues CREATE TABLE for tables that do not
    yet exist in the database. If a table (e.g. `projects`) was already
    created by a previous run and a model is later updated to add a new
    column (e.g. `github_url`), create_all() will NOT retroactively add that
    column to the pre-existing SQLite file — it silently does nothing for
    tables that already exist.

    This project intentionally has no migration framework (no Alembic, no
    migrations/ directory) — this is a dev-only walking-skeleton stage where
    schema drift is handled by recreating the local database rather than by
    writing migrations.

    If you see `sqlalchemy.exc.OperationalError: no such column: ...` after
    pulling a model change, the fix is to drop and recreate the Docker volume
    holding the SQLite file:

        docker compose down -v && docker compose up --build

    This destroys local dev data only — never run this against a production
    volume.
    """
    Base.metadata.create_all(engine)
    _migrate_ticket_statuses()


def _migrate_ticket_statuses() -> None:
    """Idempotent column additions for ticket_statuses.

    summary, issue_type, and current_status were added after the initial table
    creation. Existing Docker volumes have the old schema; create_all() won't
    touch them. This runs PRAGMA to check and ALTER only what's missing.
    ponytail: no Alembic, just PRAGMA guard — upgrade to Alembic if more tables need this
    """
    _NEW_COLS = {
        "summary": "VARCHAR(2000)",
        "issue_type": "VARCHAR(50)",
        "current_status": "VARCHAR(500)",
    }
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(ticket_statuses)"))}
        for col, col_type in _NEW_COLS.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE ticket_statuses ADD COLUMN {col} {col_type}"))
        conn.commit()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a DB session and ensure it is closed afterward.

    Usage:
        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
