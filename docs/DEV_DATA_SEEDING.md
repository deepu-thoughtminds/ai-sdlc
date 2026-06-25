# Dev Data Seeding

`docker compose down -v` wipes the named Docker volumes (`app_data`,
`freellmapi_data`) — that means your backend test project and any
freellmapi routing tweaks are gone on the next `up`. `scripts/seed_dev_data.py`
captures and restores that data so you don't have to recreate it by hand
every time.

---

## What gets seeded

| Source | Table | Why |
|--------|-------|-----|
| Backend (`app_data` volume) | `projects` | Your test Jira project (name, URL, encrypted tokens) |
| FreeLLMAPI (`freellmapi_data` volume) | `settings` | Routing config — specifically clears `active_profile_id`, which FreeLLMAPI auto-recreates on a fresh DB and which otherwise silently overrides your tuned `fallback_config` model priority order |

**Not seeded (by design):**
- `pipeline_states` (backend) — run-time state, regenerates naturally
- `api_keys`, `users`, `sessions`, `requests`, `rate_limit_usage`, `quirks*` (freellmapi) — secrets and transient data, not config
- `fallback_config` / `models` / `profiles` / `profile_models` (freellmapi) — already populated by freellmapi's own startup migration on a fresh DB; replaying a captured snapshot of those verbatim hits primary-key/foreign-key conflicts against the auto-seeded rows

The dump files (`scripts/seeds/*.sql`) are **gitignored**. They contain your
project's real Jira URL and email in plaintext columns (only the
tokens/credentials are Fernet-encrypted) — this is local working data, not
something to commit.

---

## First time after cloning the repo

There's nothing to seed yet — `scripts/seeds/*.sql` doesn't exist in a fresh
clone. Set the stack up normally:

1. `docker compose up --build`
2. Create your project via the Jira webhook flow (or the dashboard) as usual
3. Configure freellmapi routing/provider keys via the dashboard (see
   [`FREELLMAPI_SETUP.md`](./FREELLMAPI_SETUP.md))
4. Once you're happy with that state, capture it:
   ```bash
   python3 scripts/seed_dev_data.py dump
   ```

From then on, that snapshot is yours to restore on demand.

---

## Restoring after a volume wipe

```bash
docker compose down -v
docker compose up -d
# wait a few seconds for both DBs to finish their own startup migrations
python3 scripts/seed_dev_data.py seed
```

This re-creates the test project row and resets freellmapi's routing
settings to your last-dumped state. Idempotent — safe to re-run against an
already-seeded DB (`INSERT OR IGNORE` for projects, `INSERT OR REPLACE` for
settings).

You will still need to re-add provider API keys via the freellmapi
dashboard — those are intentionally not seeded.

---

## Updating the snapshot

Whenever you change the test project's details or retune freellmapi's
routing config and want that to survive future volume wipes, re-dump:

```bash
python3 scripts/seed_dev_data.py dump
```

This overwrites `scripts/seeds/backend_dump.sql` and
`scripts/seeds/freellmapi_dump.sql` with the current live state.

---

## Requirements

- The stack must be up (`docker compose up -d`) — both subcommands talk to
  the running `backend` and `freellmapi` containers via `docker compose exec`.
- Run from the repo root (so `docker compose` resolves the right project).
