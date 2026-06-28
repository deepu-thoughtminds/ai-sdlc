"""Tests for services/ticket_tracking.py (record_transaction + upsert_ticket_status).

Uses the shared mongomock fixtures in conftest.py.
"""

import pytest

from repositories import stage_transaction_repo, ticket_status_repo
from services.ticket_tracking import (
    record_transaction,
    safe_record_transaction,
    safe_upsert_ticket_status,
    upsert_ticket_status,
)
from tests.support import make_project


def test_record_transaction_appends_rows(db) -> None:
    p = make_project(db)
    record_transaction(db, p.id, "P-1", "description", "Generated description")
    record_transaction(db, p.id, "P-1", "dev", "PR sent", result_url="http://pr/1")

    rows = stage_transaction_repo.list_for_ticket(db, p.id, "P-1")
    assert len(rows) == 2
    assert {r.stage for r in rows} == {"description", "dev"}


def test_record_transaction_rejects_bad_stage_and_status(db) -> None:
    p = make_project(db)
    with pytest.raises(ValueError):
        record_transaction(db, p.id, "P-1", "bogus", "x")
    with pytest.raises(ValueError):
        record_transaction(db, p.id, "P-1", "dev", "x", status="bogus")


def test_upsert_creates_then_updates_single_row(db) -> None:
    p = make_project(db)
    upsert_ticket_status(
        db, p.id, "P-1",
        pipeline_stage="description", current_status="Ticket created",
        summary="Add login", issue_type="Story",
    )
    # Second call updates the same row (no duplicate).
    upsert_ticket_status(
        db, p.id, "P-1", pipeline_stage="dev", current_status="Coding started",
    )

    rows = ticket_status_repo.list_for_project(db, p.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.pipeline_stage == "dev"
    assert row.current_status == "Coding started"
    # summary/issue_type preserved from the first call (not clobbered)
    assert row.summary == "Add login"
    assert row.issue_type == "Story"


def test_upsert_rejects_bad_stage(db) -> None:
    p = make_project(db)
    with pytest.raises(ValueError):
        upsert_ticket_status(db, p.id, "P-1", pipeline_stage="bogus")


def test_safe_wrappers_swallow_errors(db) -> None:
    p = make_project(db)
    # Bad stage would raise in the non-safe variant; safe variant returns None.
    assert safe_record_transaction(db, p.id, "P-1", "bogus", "x") is None
    assert safe_upsert_ticket_status(db, p.id, "P-1", pipeline_stage="bogus") is None
    # A subsequent valid call still works.
    assert safe_record_transaction(db, p.id, "P-1", "dev", "ok") is not None
