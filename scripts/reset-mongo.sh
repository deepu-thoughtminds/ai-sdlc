#!/usr/bin/env bash
# Wipe the local MongoDB data and start fresh.
#
# Drops the `mongo_data` Docker volume (the only place app data lives) and brings
# Mongo back up; the backend recreates empty collections + indexes on its next
# startup. Use this to reset state between test runs.
#
#   bash scripts/reset-mongo.sh
#
# PowerShell equivalent:
#   docker compose down -v; docker compose up -d mongo mongo-init
#
# Targeted cleanup (keep the DB, clear one collection) instead of a full wipe:
#   docker compose exec mongo mongosh aisdlc --eval "db.stage_transactions.deleteMany({})"
#
# Note: per-document deletes free logical space but WiredTiger does not return
# disk to the OS until the volume is dropped (which this script does).
set -euo pipefail

echo "Stopping stack and removing volumes (mongo_data will be deleted)..."
docker compose down -v

echo "Starting MongoDB (single-node replica set) and initialising..."
docker compose up -d mongo mongo-init

echo "Done. MongoDB is empty; start the backend to recreate collections + indexes:"
echo "  docker compose up -d backend"
