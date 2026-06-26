---
id: "27-01"
phase: "27"
title: "Create app_container.py service"
status: complete
completed: "2026-06-26"
commits:
  - "3858572 feat(27-01): add backend/services/app_container.py — SERVE-01..04"
  - "fb95703 test(27-01): add backend/tests/test_app_container.py — 20 tests for SERVE-01..04"
key-files:
  created:
    - backend/services/app_container.py
    - backend/tests/test_app_container.py
  modified: []
requirements-covered:
  - SERVE-01
  - SERVE-02
  - SERVE-03
  - SERVE-04
---

## What Was Built

A subprocess-only `managed_app_container` context manager in `backend/services/app_container.py` that:

- **SERVE-01** — `_detect_serve_command` reads `package.json` and prefers `preview` > `start` > `dev`, logs the chosen command at INFO, raises `ValueError` when none are present.
- **SERVE-02** — `_start_container` invokes `docker run -d --rm --name <name> --network <net> -p 0:<port> -v <ws>:/app -w /app <image> sh -c <script>` in list-form argv (no shell=True). `_build_serve_script` adds `npm run build` only when a `build` script exists.
- **SERVE-03** — `_wait_until_healthy` polls `GET /` via httpx with a configurable deadline (default 60s via `APP_CONTAINER_HEALTH_TIMEOUT`); raises `ContainerStartError` on timeout.
- **SERVE-04** — `managed_app_container` uses a `started` flag and a `finally` block so `_remove_container` (which issues `docker rm -f` and never raises) is called on every exit path except when `_detect_serve_command` raised before any container was started.

The yielded URL is the network-internal `http://<name>:<container_port>`, reachable by the backend and sibling containers on `ai-sdlc-net` via Docker DNS. The dynamic host port (`-p 0:PORT`) is published for debugging only.

## Test Results

```
20 passed in 0.05s
```

All SERVE-01..04 behaviours covered. No Docker daemon, no network, no real sleep required.

## Deviations

None. Implementation matches the plan exactly:
- Purely additive — no existing files modified.
- No new dependencies (`httpx` already in `requirements.txt`).
- Container name derived from `uuid4().hex[:8]` — no external input in list-form argv.

## Self-Check: PASSED

- [x] SERVE-01: `_detect_serve_command` prefers preview>start>dev, raises ValueError when none exist.
- [x] SERVE-02: `docker run` argv is list-form with `-d`, `--rm`, `--name`, `--network`, `-p 0:PORT`, `-v ws:/app`.
- [x] SERVE-03: `_wait_until_healthy` returns on 200, raises `ContainerStartError` on timeout.
- [x] SERVE-04: `docker rm -f` called on success, `ContainerStartError`, arbitrary exception; NOT called when no container was started.
- [x] `ContainerStartError(RuntimeError)` defined in module.
- [x] `python -m pytest tests/test_app_container.py -v` — 20/20 passed.
