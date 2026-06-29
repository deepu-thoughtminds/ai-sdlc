#!/usr/bin/env python3
"""Drop all collections in the aisdlc MongoDB database.

Usage (run from repo root, mongo container must be up):
    python3 scripts/clear_db.py          # prompts for confirmation
    python3 scripts/clear_db.py --yes    # skip confirmation
"""

import os
import sys

from pymongo import MongoClient

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/?replicaSet=rs0")
MONGODB_DB = os.environ.get("MONGODB_DB", "aisdlc")

COLLECTIONS = [
    "projects",
    "ticket_statuses",
    "stage_transactions",
    "pipeline_states",
    "agent_events",
    "counters",
]


def main() -> None:
    skip_confirm = "--yes" in sys.argv

    if not skip_confirm:
        answer = input(f"Drop all collections in '{MONGODB_DB}' at {MONGODB_URI}? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)

    db = MongoClient(MONGODB_URI)[MONGODB_DB]
    for name in COLLECTIONS:
        result = db[name].delete_many({})
        print(f"  {name}: {result.deleted_count} documents deleted")

    print("Done.")


if __name__ == "__main__":
    main()
