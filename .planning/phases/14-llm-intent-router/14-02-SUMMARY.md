---
plan: 14-02
phase: 14-llm-intent-router
status: complete
completed: 2026-06-20
commit: 67d2302

key-files:
  modified:
    - backend/routers/webhook.py
    - backend/tests/test_mention_parser.py
    - backend/tests/test_webhook.py
  created:
    - backend/tests/test_intent_router.py
---

## Summary

Wired the Phase 14-01 LLM intent classifier into the live event pipeline and delivered comprehensive unit tests covering all intent paths without live API keys.

### What was built

**webhook.py** — all `mention_result.stage` renamed to `mention_result.action` (9 occurrences); stub handlers added for `start_coding` (pending Phase 16) and `merge_pr` (pending Phase 17); unrecognized-intent help comment posted when `@jarvis` appears in body but `classify_intent` returns None (INTENT-02); approve subcmd now reads `entities.get("target", extra)`.

**test_intent_router.py** (new, 11 tests) — covers start_coding, merge_pr, assign with entity extraction, unknown action, low confidence, malformed JSON, LLM exception, markdown-fenced JSON.

**test_mention_parser.py** (rewritten, 10 tests) — all tests mock `classify_intent`; covers describe (now valid action), architecture, assign extra field, unrecognized intent, approve, start_coding, merge_pr.

**test_webhook.py** — 4 new tests (unknown-intent help comment, no-@jarvis silent ignore, start_coding stub, merge_pr stub); 8 existing tests updated to mock `parse_mention` and avoid live LLM calls.

### Self-Check: PASSED

- `grep -c "result\.stage" routers/webhook.py` → 0
- `grep -c "result\.action" routers/webhook.py` → 9
- `grep -c "KNOWN_STAGES" backend/` → 0 (constant)
- `pytest tests/test_intent_router.py tests/test_mention_parser.py tests/test_webhook.py` → **41 passed, 0 failed**
- help comment path: `intent_unknown` present in webhook.py
- LLM failure degradation: `test_classify_llm_raises` passes — returns None, no exception
