"""Throwaway demo seeder for manually testing the ticket status / transaction
read APIs without a live Jira/GitHub/LLM flow.

Run inside the backend container (backend/ is bind-mounted to /app):

    docker compose exec backend python seed_demo.py

Adjust PROJECT_ID / TICKET below to match a project you created via
POST /api/projects. Safe to re-run: it clears this ticket's rows first.
Delete this file when you're done testing.
"""

from database import get_database
from repositories import stage_transaction_repo, ticket_status_repo

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
    db = get_database()

    # Idempotent: remove any prior rows for this ticket so re-runs are clean.
    db["stage_transactions"].delete_many(
        {"project_id": PROJECT_ID, "ticket_key": TICKET}
    )
    db["ticket_statuses"].delete_many(
        {"project_id": PROJECT_ID, "ticket_key": TICKET}
    )

    ticket_status_repo.upsert(
        db,
        PROJECT_ID,
        TICKET,
        pipeline_stage="qa",
        current_status="QA pipeline completed",
        summary="Add login page",
        issue_type="Story",
    )
    for stage, event, url in TRANSACTIONS:
        stage_transaction_repo.append(
            db, PROJECT_ID, TICKET, stage, event, status="success", result_url=url
        )

    print(f"seeded ticket {TICKET} for project {PROJECT_ID} "
          f"with {len(TRANSACTIONS)} transactions")


if __name__ == "__main__":
    main()
