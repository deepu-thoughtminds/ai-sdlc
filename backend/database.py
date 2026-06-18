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

from sqlalchemy import create_engine
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
    """
    Base.metadata.create_all(engine)


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
