---
id: "10-02"
phase: "10"
plan: "Unit tests for complexity_classifier (boundary cases + parse isolation)"
status: "complete"
completed_at: "2026-06-19"
commits:
  - "feat(10-02): add unit tests for complexity_classifier"
key-files:
  created:
    - "backend/tests/test_complexity_classifier.py"
---

# Summary: Plan 10-02 — Unit Tests for Complexity Classifier

## What Was Built

Created `backend/tests/test_complexity_classifier.py` with 6 tests covering all boundary cases, parse isolation, malformed JSON handling, and DB persistence for `classify_complexity()`.

## Tasks Completed

### Task 1 — Write test_complexity_classifier.py

6 tests written and passing:

| Test | Scenario | Result |
|------|----------|--------|
| `test_classify_small_below_threshold` | component_count=1 → "small" | ✓ |
| `test_classify_complex_at_threshold` | component_count=2 → "complex" | ✓ |
| `test_classify_complex_above_threshold` | component_count=3 → "complex" | ✓ |
| `test_classify_malformed_json_defaults_to_small` | bad JSON → graceful default | ✓ |
| `test_build_classify_prompt_contains_rubric_and_schema` | pure prompt structure test, no mock | ✓ |
| `test_classify_persists_to_pipeline_state_when_row_exists` | DB persistence path (CLASSIFY-02) | ✓ |

Setup pattern: StaticPool in-memory SQLite, `reset_tables` autouse fixture, all LLM calls mocked at `"services.complexity_classifier.route_request"`.

## Test Results

```
cd backend && python3 -m pytest tests/test_complexity_classifier.py -x -q
6 passed in 0.26s
```

## Deviations

- Fix required in `_insert_project` helper: `projects.github_token` has a NOT NULL constraint — added `github_token=encrypt_credential("gh-tok")` to the project fixture.
- Pre-existing failure in `test_approval_detector.py::test_detect_and_apply_approval_architecture_stage_posts_comment` is unrelated to Phase 10 (confirmed: fails on clean HEAD before any Phase 10 changes).

## Self-Check

- [x] 6 tests collected, all pass under `python3 -m pytest tests/test_complexity_classifier.py -x -q`
- [x] `_build_classify_prompt` tested independently without any LLM mock
- [x] Malformed JSON test confirms no exception is raised
- [x] At least one test inserts a real PipelineState row and asserts `.complexity` and `.complexity_rationale`
- [x] Patch path: `"services.complexity_classifier.route_request"` throughout
- [x] No real httpx calls (route_request fully mocked)
