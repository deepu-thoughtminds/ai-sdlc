#!/usr/bin/env bash
# OBSOLETE: MongoDB now lives on MongoDB Atlas, not a local Docker volume.
#
# There is no `mongo_data` volume to drop anymore. To clear application data on
# Atlas, use clear_db.py (it reads MONGODB_URI/MONGODB_DB from the backend
# container's env, so it targets whatever Atlas database the stack is pointed at):
#
#   docker compose exec backend python scripts/clear_db.py          # prompts
#   docker compose exec backend python scripts/clear_db.py --yes    # no prompt
#
# The backend recreates empty collections + indexes on its next startup.
#
# Targeted cleanup of a single collection (keep the rest):
#   docker compose exec backend python -c \
#     "import os; from pymongo import MongoClient; \
#      MongoClient(os.environ['MONGODB_URI'])[os.environ.get('MONGODB_DB','aisdlc')] \
#      ['stage_transactions'].delete_many({})"
echo "reset-mongo.sh is obsolete — MongoDB is on Atlas now."
echo "Use: docker compose exec backend python scripts/clear_db.py"
exit 0
