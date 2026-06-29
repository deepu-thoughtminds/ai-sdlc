#!/usr/bin/env python3
"""Drop all collections in the aisdlc MongoDB database.

Usage (run from repo root, containers must be up):
    python3 scripts/clear_db.py          # prompts for confirmation
    python3 scripts/clear_db.py --yes    # skip confirmation
"""

import os
import subprocess
import sys

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://mongo:27017/?replicaSet=rs0")
MONGODB_DB = os.environ.get("MONGODB_DB", "aisdlc")

COLLECTIONS = [
    "projects",
    "ticket_statuses",
    "stage_transactions",
    "pipeline_states",
    "agent_events",
    "counters",
]

INNER_SCRIPT = """
import os, json
from pymongo import MongoClient
uri = os.environ.get("MONGODB_URI", "mongodb://mongo:27017/?replicaSet=rs0")
db_name = os.environ.get("MONGODB_DB", "aisdlc")
db = MongoClient(uri)[db_name]
collections = {collections}
for name in collections:
    n = db[name].delete_many({{}}).deleted_count
    print(f"  {{name}}: {{n}} documents deleted")
print("Done.")
""".format(collections=COLLECTIONS)


def main() -> None:
    skip_confirm = "--yes" in sys.argv

    if not skip_confirm:
        answer = input(f"Drop all collections in '{MONGODB_DB}'? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)

    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python3"],
        input=INNER_SCRIPT,
        text=True,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
