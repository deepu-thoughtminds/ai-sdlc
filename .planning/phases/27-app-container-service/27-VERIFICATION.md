---
phase: 27-app-container-service
verified: 2026-06-26T12:00:00Z
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 27: App Container Service Verification Report

**Phase Goal:** The QA pipeline can reliably start the target app in an isolated container, confirm it is reachable, and always clean up — before any test generation touches the live URL
**Verified:** 2026-06-26
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `app_container.py` reads `package.json` scripts and selects `preview` over `start` over `dev`; chosen command is logged and traceable | ✓ VERIFIED | `_detect_serve_command` iterates `_SERVE_PREFERENCE = ["preview", "start", "dev"]`, returns first match, logs at INFO (line 60); 3 behavioral tests pass: `test_detect_serve_command_prefers_preview`, `_falls_back_to_start`, `_falls_back_to_dev` |
| 2 | Docker container joins the compose network and serves the app on a dynamically allocated host port — no port conflicts | ✓ VERIFIED | `_start_container` argv (lines 98–107): `docker run -d --rm --name <n> --network <net> -p 0:<port> -v <ws>:/app -w /app <image> sh -c <script>` — `-p 0:PORT` lets Docker assign the host port dynamically; `test_start_container_argv_contains_required_flags` asserts all required flags in list-form argv |
| 3 | `GET /` polled against the container URL returns HTTP 200 before `app_container.py` yields the live URL; `ContainerStartError` raised on timeout | ✓ VERIFIED | `_wait_until_healthy` (lines 133–146) uses `time.monotonic()` deadline, polls `httpx.get(url, timeout=5.0)`, swallows `httpx.RequestError`, returns on 200, raises `ContainerStartError` on deadline; `managed_app_container` calls it before `yield url` (line 212–214); 4 behavioral tests pass: `_returns_on_200`, `_ignores_non_200`, `_swallows_request_error`, `_raises_on_timeout` |
| 4 | Container removed in `finally` block on every exit path (success, failure, timeout, exception); no orphaned containers | ✓ VERIFIED | `managed_app_container` (lines 205–217): `started` flag set to `True` before `_start_container`; `finally: if started: _remove_container(name)`; `_remove_container` calls `["docker", "rm", "-f", name]` and never raises (lines 154–164); `docker run --rm` provides secondary cleanup if process is killed; 4 behavioral tests cover: success path, `ContainerStartError` during health-check, arbitrary exception in body, and verify NO rm call when `_detect_serve_command` raises before container starts |

**Score:** 4/4 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/services/app_container.py` | AppContainer service module | ✓ VERIFIED | 218 lines; defines `ContainerStartError(RuntimeError)`, `_detect_serve_command`, `_build_serve_script`, `_start_container`, `_wait_until_healthy`, `_remove_container`, `managed_app_container` |
| `backend/tests/test_app_container.py` | Test suite, all SERVE-01..04 covered | ✓ VERIFIED | 332 lines; 20 tests collected; 20 passed in 0.03s |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `managed_app_container` | `_detect_serve_command` | direct call line 207 | ✓ WIRED | Reads `package.json` via `pathlib.Path`; raises `ValueError` before `started = True` |
| `managed_app_container` | `_start_container` | direct call line 210 | ✓ WIRED | Called after `started = True`; teardown runs if this raises |
| `managed_app_container` | `_wait_until_healthy` | direct call line 212 | ✓ WIRED | Called before `yield url`; URL not surfaced until 200 confirmed |
| `managed_app_container` | `_remove_container` (finally) | `finally` block line 215–217 | ✓ WIRED | `if started: _remove_container(name)` — guards against no-container case |
| `_remove_container` | `subprocess.run(["docker","rm","-f",name])` | direct call lines 157–159 | ✓ WIRED | List-form argv, never raises, non-zero returncode logged at DEBUG |
| `_start_container` | `subprocess.run(["docker","run","-d",…])` | direct call line 108 | ✓ WIRED | List-form argv confirmed; no `shell=True` anywhere in module |
| `_wait_until_healthy` | `httpx.get(url, timeout=5.0)` | direct call line 138 | ✓ WIRED | `httpx.RequestError` swallowed; returns on `status_code == 200` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 20-test suite passes | `python3 -m pytest tests/test_app_container.py -v` | `20 passed in 0.03s` | ✓ PASS |
| Module imports clean | `python3 -c "from services.app_container import ContainerStartError, _detect_serve_command, managed_app_container; print('import-ok')"` | `import-ok` | ✓ PASS |
| Commits exist in repo | `git log --oneline \| grep -E "3858572\|fb95703"` | both hashes found | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SERVE-01 | 27-01 | Detect serve command from `package.json` (`preview` > `start` > `dev`) | ✓ SATISFIED | `_detect_serve_command` + 5 covering tests |
| SERVE-02 | 27-01 | Build and serve in ephemeral container on compose network, dynamic host port | ✓ SATISFIED | `_start_container` argv verified; `_build_serve_script` conditional build verified |
| SERVE-03 | 27-01 | Poll `GET /` until HTTP 200 or `ContainerStartError` on timeout | ✓ SATISFIED | `_wait_until_healthy` + 4 covering tests |
| SERVE-04 | 27-01 | Container removed in `finally` on all exit paths | ✓ SATISFIED | `started` flag + `finally` block + 4 covering tests including no-rm-on-detect-fail |

### Anti-Patterns Found

None. No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, or `PLACEHOLDER` markers found in either file. No `shell=True` in any `subprocess.run` call. No empty return stubs or hardcoded empty data.

### Plan must_haves Checklist

All 6 PLAN must_haves from `27-01-PLAN.md`:

| Must-have | Status | Evidence |
|-----------|--------|----------|
| `_detect_serve_command` prefers preview > start > dev, raises `ValueError` when none | ✓ VERIFIED | Lines 58–63; 3 positive tests + 2 negative tests |
| `docker run` argv list-form with `-d`, `--name`, `--network`, `-p 0:PORT`, `-v ws:/app`, image | ✓ VERIFIED | Lines 98–107; `test_start_container_argv_contains_required_flags` |
| `_wait_until_healthy` returns on 200, raises `ContainerStartError` on timeout | ✓ VERIFIED | Lines 133–146; 4 covering tests |
| `managed_app_container` calls `docker rm -f` in `finally` on all exit paths | ✓ VERIFIED | Lines 205–217; 4 behavioral teardown tests |
| `ContainerStartError(RuntimeError)` defined in module | ✓ VERIFIED | Lines 40–41 |
| `backend/tests/test_app_container.py` covers SERVE-01..04, mocked, no real Docker | ✓ VERIFIED | 20 tests, 0.03s, no real subprocess or network calls |

### Human Verification Required

None. All must-haves and success criteria are verified by behavioral tests that exercise real code paths (not just presence). The SERVE-04 teardown invariant is explicitly tested in 4 separate scenarios via mock-verified `subprocess.run` call assertions.

---

_Verified: 2026-06-26T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
