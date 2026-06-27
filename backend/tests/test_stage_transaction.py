"""Tests for the stage_transactions collection and its Pydantic schemas.

Uses the shared mongomock fixtures in conftest.py.
"""

from datetime import datetime

import pytest

from models.stage_transaction import StageTransactionCreate, StageTransactionPublic
from repositories import stage_transaction_repo
from tests.support import make_project


def test_stage_transaction_create_and_read(db) -> None:
    p = make_project(db)
    txn = stage_transaction_repo.append(
        db, p.id, "P-1", "dev", "Coding finished and PR sent",
        status="success", result_url="https://github.com/acme/x/pull/3",
    )
    assert isinstance(txn.id, int)
    assert isinstance(txn.created_at, datetime)
    assert txn.result_url.endswith("/pull/3")
    assert txn.detail is None


def test_multiple_transactions_ordered_by_created_at(db) -> None:
    p = make_project(db)
    for stage, event in [
        ("description", "Generated description"),
        ("architecture", "Published to Confluence"),
        ("dev", "PR sent"),
    ]:
        stage_transaction_repo.append(db, p.id, "P-1", stage, event, status="success")

    rows = stage_transaction_repo.list_for_ticket(db, p.id, "P-1")
    assert [r.stage for r in rows] == ["description", "architecture", "dev"]


def test_public_schema_round_trip(db) -> None:
    p = make_project(db)
    txn = stage_transaction_repo.append(
        db, p.id, "P-1", "merge", "PR merged", status="success"
    )
    pub = StageTransactionPublic.model_validate(txn)
    assert pub.stage == "merge"
    assert pub.event == "PR merged"
    # project_id is internal and not exposed in the public schema
    assert not hasattr(pub, "project_id")


def test_create_schema_rejects_invalid_stage() -> None:
    with pytest.raises(ValueError):
        StageTransactionCreate(ticket_key="P-1", stage="bogus", event="x")


def test_create_schema_rejects_invalid_status() -> None:
    with pytest.raises(ValueError):
        StageTransactionCreate(ticket_key="P-1", stage="dev", event="x", status="bogus")
