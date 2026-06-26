"""Throwaway demo seeder for manually testing the ticket status / transaction
read APIs without a live Jira/GitHub/LLM flow.

Run inside the backend container (backend/ is bind-mounted to /app):

    docker compose exec backend python seed_demo.py

Adjust PROJECT_ID / TICKET below to match a project you created via
POST /api/projects. Safe to re-run: it clears this ticket's rows first.
Delete this file when you're done testing.
"""

from database import SessionLocal
from models.project import Project  # noqa: F401 — registers the mapper TicketStatus relates to
from models.stage_transaction import StageTransaction
from models.ticket_status import TicketStatus

# --- edit these to match your project ---
PROJECT_ID = 1
TICKET = "DEMO-1"
# ----------------------------------------

# Each row: (stage, event message, result_url)
TRANSACTIONS = [
    ("description", "Generated description and inserted to ticket", None),
    ("architecture", "Design/Architecture published to Confluence page",
     "https://demo.atlassian.net/wiki/x"),
    ("dev", "Coding started", None),
    ("dev", "Coding finished and PR sent", "https://github.com/acme/demo/pull/1"),
    ("merge", "PR merged", "https://github.com/acme/demo/pull/1"),
    ("qa", "QA pipeline completed", None),
]


def main() -> None:
    db = SessionLocal()
    try:
        # Idempotent: remove any prior rows for this ticket so re-runs are clean.
        db.query(StageTransaction).filter(
            StageTransaction.project_id == PROJECT_ID,
            StageTransaction.ticket_key == TICKET,
        ).delete()
        db.query(TicketStatus).filter(
            TicketStatus.project_id == PROJECT_ID,
            TicketStatus.ticket_key == TICKET,
        ).delete()
        db.commit()

        db.add(TicketStatus(
            project_id=PROJECT_ID,
            ticket_key=TICKET,
            pipeline_stage="qa",
            current_status="QA pipeline completed",
            summary="Add login page",
            issue_type="Story",
        ))
        for stage, event, url in TRANSACTIONS:
            db.add(StageTransaction(
                project_id=PROJECT_ID,
                ticket_key=TICKET,
                stage=stage,
                event=event,
                status="success",
                result_url=url,
            ))
        db.commit()
        print(f"seeded ticket {TICKET} for project {PROJECT_ID} "
              f"with {len(TRANSACTIONS)} transactions")
    finally:
        db.close()


if __name__ == "__main__":
    main()
