#!/usr/bin/env python3
"""Dev-data seeding for the backend (MongoDB) and freellmapi SQLite databases.

Both DBs live in named Docker volumes (app_data, freellmapi_data) that get
wiped by `docker compose down -v`. This script captures a snapshot of the
useful rows ("dump") and re-applies them ("seed") after a fresh volume comes
up, so you don't have to re-create the test project or re-tune freellmapi's
routing config by hand every time.

Dump output goes to scripts/seeds/*.json / *.sql, which is gitignored — those
files contain the project's real Jira URL/email (plaintext columns) and are
local working data, not something to commit.

Usage (run from repo root, containers must be up):
    python3 scripts/seed_dev_data.py dump   # snapshot current DB state
    python3 scripts/seed_dev_data.py seed   # re-apply snapshot (idempotent)
"""

import json
import subprocess
import sys
from pathlib import Path

SEEDS_DIR = Path(__file__).parent / "seeds"
BACKEND_DUMP = SEEDS_DIR / "backend_dump.json"
FREELLMAPI_DUMP = SEEDS_DIR / "freellmapi_dump.sql"
FREELLMAPI_ROUTING_DUMP = SEEDS_DIR / "freellmapi_routing.sql"

# freellmapi tables worth seeding: `settings` (routing config — see seed()'s
# active_profile_id handling) and `api_keys` (provider keys). api_keys is
# safe to dump/replay because FREELLMAPI_ENCRYPTION_KEY lives in .env on the
# host, not in the wiped freellmapi_data volume — the encrypted_key/iv/
# auth_tag blobs in the dump stay decryptable across a volume wipe as long as
# .env is untouched. Still gitignored: ciphertext only, never plaintext, but
# still a credential artifact you don't want in git history.
#
# fallback_config/models/profiles/profile_models are excluded from raw
# table replay — already populated by freellmapi's own startup migration on
# a fresh DB (with their own autoincrement ids), so replaying a captured
# snapshot of those verbatim hits FK/PK conflicts. The custom priority order
# within fallback_config (which model is tried first) is instead captured
# separately in freellmapi_routing.sql as UPDATE statements keyed by
# (platform, model_id) rather than raw row id — portable across catalog
# version changes. See dump()/seed() below.
FREELLMAPI_TABLES = ["settings", "api_keys"]


def run(cmd: list[str], **kwargs) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs)
    return result.stdout


def run_script(cmd: list[str], script: str) -> str:
    """Like run(), but feeds `script` over stdin instead of -c/-e args —
    avoids "Argument list too long" once dumps grow past a few KB."""
    result = subprocess.run(cmd, input=script, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed:\n{result.stderr}")
    return result.stdout


def dump() -> None:
    SEEDS_DIR.mkdir(exist_ok=True)

    backend_script = """
import json, datetime
from pymongo import MongoClient
def _serial(v):
    if isinstance(v, datetime.datetime): return v.isoformat()
    if isinstance(v, datetime.date): return v.isoformat()
    raise TypeError(type(v))
client = MongoClient('mongodb://mongo:27017')
docs = list(client['aisdlc']['projects'].find())
for d in docs:
    if not isinstance(d.get('_id'), (int, float, str, bool)):
        d['_id'] = str(d['_id'])  # make ObjectId JSON-serialisable
with open('/tmp/backend_dump.json', 'w') as f:
    for d in docs:
        f.write(json.dumps(d, default=_serial) + '\\n')
"""
    run_script(["docker", "compose", "exec", "-T", "backend", "python3"], backend_script)
    run(["docker", "compose", "cp", "backend:/tmp/backend_dump.json", str(BACKEND_DUMP)])

    freellmapi_script = """
const Database = require('better-sqlite3');
const fs = require('fs');
const db = new Database('/app/server/data/freeapi.db', { readonly: true });
const tables = %s;
let out = [];
for (const t of tables) {
  const rows = db.prepare('SELECT * FROM "' + t + '"').all();
  for (const row of rows) {
    const cols = Object.keys(row);
    const vals = cols.map(c => {
      const v = row[c];
      if (v === null) return 'NULL';
      if (typeof v === 'number') return String(v);
      if (Buffer.isBuffer(v)) return "X'" + v.toString('hex') + "'";
      return "'" + String(v).replace(/'/g, "''") + "'";
    });
    out.push('INSERT INTO "' + t + '" (' + cols.map(c => '"' + c + '"').join(',') + ') VALUES (' + vals.join(',') + ');');
  }
}
fs.writeFileSync('/tmp/freellmapi_dump.sql', out.join('\\n'));
""" % (FREELLMAPI_TABLES)
    run_script(["docker", "compose", "exec", "-T", "freellmapi", "node"], freellmapi_script)
    run(["docker", "compose", "cp", "freellmapi:/tmp/freellmapi_dump.sql", str(FREELLMAPI_DUMP)])

    # Custom fallback_config priority/enabled order, captured by
    # (platform, model_id) — not raw row id — so it survives the catalog
    # being re-seeded with different autoincrement ids on a fresh DB.
    routing_script = """
const Database = require('better-sqlite3');
const fs = require('fs');
const db = new Database('/app/server/data/freeapi.db', { readonly: true });
const rows = db.prepare(`
  SELECT m.platform, m.model_id, fc.priority, fc.enabled
  FROM fallback_config fc JOIN models m ON m.id = fc.model_db_id
`).all();
const out = rows.map(r => `UPDATE fallback_config SET priority=${r.priority}, enabled=${r.enabled} WHERE model_db_id = (SELECT id FROM models WHERE platform='${r.platform}' AND model_id='${r.model_id.replace(/'/g, "''")}');`);
fs.writeFileSync('/tmp/freellmapi_routing.sql', out.join('\\n'));
"""
    run_script(["docker", "compose", "exec", "-T", "freellmapi", "node"], routing_script)
    run(["docker", "compose", "cp", "freellmapi:/tmp/freellmapi_routing.sql", str(FREELLMAPI_ROUTING_DUMP)])

    print(f"Dumped {BACKEND_DUMP}, {FREELLMAPI_DUMP}, and {FREELLMAPI_ROUTING_DUMP}")


def seed() -> None:
    if not BACKEND_DUMP.exists() or not FREELLMAPI_DUMP.exists() or not FREELLMAPI_ROUTING_DUMP.exists():
        sys.exit(f"Missing seed files — run `python3 {__file__} dump` first while the old data is still up.")

    docs_json = BACKEND_DUMP.read_text()
    backend_script = f"""
import json
from pymongo import MongoClient
client = MongoClient('mongodb://mongo:27017')
col = client['aisdlc']['projects']
docs = [json.loads(line) for line in {docs_json!r}.splitlines() if line.strip()]
for d in docs:
    col.replace_one({{'_id': d['_id']}}, d, upsert=True)
print('backend seeded:', len(docs), 'docs')
"""
    run_script(["docker", "compose", "exec", "-T", "backend", "python3"], backend_script)

    # Replace (not ignore) settings rows: the dump is the desired state, and
    # the one row we actively want gone (active_profile_id, auto-seeded on a
    # fresh DB) is absent from the dump by construction — so it needs an
    # explicit delete, a plain replay would just leave it untouched.
    freellmapi_sql = FREELLMAPI_DUMP.read_text().replace("INSERT INTO", "INSERT OR REPLACE INTO")
    freellmapi_script = f"""
const Database = require('better-sqlite3');
const db = new Database('/app/server/data/freeapi.db');
db.prepare("DELETE FROM settings WHERE key = 'active_profile_id'").run();
db.exec({freellmapi_sql!r});
console.log('freellmapi seeded');
"""
    run_script(["docker", "compose", "exec", "-T", "freellmapi", "node"], freellmapi_script)

    # Apply custom fallback_config priority/enabled order. UPDATE-by-name,
    # not raw row replay, so models absent from this catalog version (the
    # subquery returns NULL) are silently skipped instead of erroring.
    routing_sql = FREELLMAPI_ROUTING_DUMP.read_text()
    routing_script = f"""
const Database = require('better-sqlite3');
const db = new Database('/app/server/data/freeapi.db');
db.exec({routing_sql!r});
console.log('routing order applied');
"""
    run_script(["docker", "compose", "exec", "-T", "freellmapi", "node"], routing_script)

    print("Seed complete.")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("dump", "seed"):
        sys.exit(f"Usage: python3 {sys.argv[0]} [dump|seed]")
    {"dump": dump, "seed": seed}[sys.argv[1]]()


if __name__ == "__main__":
    main()
