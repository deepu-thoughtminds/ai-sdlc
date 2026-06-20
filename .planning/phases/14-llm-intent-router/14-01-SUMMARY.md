---
plan: 14-01
phase: 14-llm-intent-router
status: complete
completed: 2026-06-20
commit: c435f26

key-files:
  created:
    - backend/services/intent_router.py
  modified:
    - backend/services/mention_parser.py
---

## Summary

Created `backend/services/intent_router.py` and rewrote `backend/services/mention_parser.py` to replace the static `KNOWN_STAGES` whitelist with LLM-powered free-text intent classification.

### What was built

**`intent_router.py` (new):**
- `VALID_ACTIONS = frozenset({"describe", "architecture", "start_coding", "merge_pr", "assign", "approve"})`
- `IntentResult(action, confidence, entities)` dataclass
- `classify_intent(mention_text)` — calls `route_request("classify", prompt)`, parses JSON response, returns `IntentResult` when confidence ≥ 0.5, `None` otherwise. Catches all exceptions and degrades gracefully to `None`.

**`mention_parser.py` (rewritten):**
- `KNOWN_STAGES` constant removed
- `APPROVE_SUBCMDS` frozenset removed
- `MentionResult` updated: `stage` field renamed to `action`, `entities: dict` field added
- `parse_mention()` rewired to call `classify_intent(mention_text)` for LLM-based classification
- `extra` field preserved for backward compatibility with `assign_pipeline.py`

### Key decisions

- `extra` field kept in `MentionResult` holding the trailing text after the first keyword (e.g. `"@alice"` for `@jarvis assign @alice`), maintaining backward compatibility with `assign_pipeline.py` which uses `mention_result.extra.lstrip("@").strip()`.
- LLM prompt instructs extraction of structured entities: `{"target": "<text>"}` for approve, `{"user": "<name>"}` for assign.
- Markdown code fence stripping added to handle LLMs that wrap JSON in ``` blocks.

### Self-Check: PASSED

- `from services.intent_router import IntentResult, classify_intent, VALID_ACTIONS` — imports OK
- `from services.mention_parser import MentionResult, parse_mention` — imports OK
- `KNOWN_STAGES` no longer exists as module attribute in `mention_parser`
- `MentionResult.action` replaces `.stage`
- `classify_intent` called in `mention_parser.parse_mention`
- `route_request` called in `intent_router.classify_intent`
- Commit: `feat(14-01): create intent_router + rewrite mention_parser to use LLM classification`
