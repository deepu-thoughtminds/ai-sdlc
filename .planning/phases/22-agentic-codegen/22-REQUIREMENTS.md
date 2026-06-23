# Phase 22: Agentic Codegen — Requirements

**Milestone:** v1.7  
**Status:** Pending  
**Goal:** Replace the freellmapi one-shot text-completion codegen path with a fully agentic coding loop so the dev pipeline handles any story complexity — from single-line text changes to multi-file architectural features — without Anthropic API costs.

---

## Requirements

### REQ-22-01: LiteLLM Proxy Service
Add a `litellm` Docker Compose service that:
- Exposes `/v1/messages` in Anthropic API format (for Claude Agent SDK)
- Translates all requests to OpenAI-compatible format and forwards to `freellmapi:3001`
- Uses `litellm/config.yaml` for model routing (two model slots for load-balance/failover)
- Pins image to `ghcr.io/berriai/litellm:main-latest` at version `>=1.82.9`
- Declares `depends_on: freellmapi`

### REQ-22-02: LiteLLM Model Config
Create `litellm/config.yaml` that:
- Maps `model_name: sonnet` to `openai/llama-3.3-70b-versatile` via freellmapi (primary — best free tool-use)
- Maps `model_name: sonnet` (second entry) to `openai/gemini-2.0-flash` via freellmapi (failover — large context)
- Sets `api_base: http://freellmapi:3001/v1` and `api_key: dummy` for both entries

### REQ-22-03: Agentic Coder Service
Create `backend/services/agentic_coder.py` with an `async def run_agentic_codegen(workspace_path, issue_key, issue_summary, issue_description, architecture_content, directory_tree)` function that:
- Uses `claude-agent-sdk` (`from claude_agent_sdk import query, ClaudeAgentOptions`)
- Sets `ANTHROPIC_BASE_URL=http://litellm:4000` and `ANTHROPIC_AUTH_TOKEN=sk-litellm-local`
- Sets `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` (strips beta headers that cause 400s on non-Anthropic providers)
- Does NOT set `ANTHROPIC_API_KEY` (would override the proxy routing)
- Sets `permission_mode="acceptEdits"`, `max_turns=30`
- Sets `allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"]`
- Builds a clear task prompt from issue metadata + architecture content + directory tree
- Returns list of `FileChange(path, content)` objects derived from files written in the workspace

### REQ-22-04: Dev Pipeline Integration
Update `backend/services/dev_pipeline.py` to:
- Remove the `if os.environ.get("CLAUDE_API_KEY"):` branch entirely
- Replace both `run_claude_code_executor()` and `generate_code_changes()` calls with a single `run_agentic_codegen()` call
- Keep all surrounding pipeline logic unchanged (clone, relevant_files, commit, PR)

### REQ-22-05: Dependency Declaration
Update `backend/requirements.txt` to add `claude-agent-sdk` (latest stable).

### REQ-22-06: Environment Documentation
Update `.env.example` (if it exists) to document:
- `LITELLM_MASTER_KEY=sk-litellm-local` — LiteLLM auth token (also used as ANTHROPIC_AUTH_TOKEN)
- No `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` needed

### REQ-22-07: Execution Order Contract
The `run_agentic_codegen()` function must run AFTER `clone_repository()` completes and BEFORE `apply_commit_push_and_open_pr()`. The agent operates directly on `cloned.workspace_path` — no separate file-change list parsing is needed since the agent writes files in place.

---

## Constraints

- No Anthropic API key required at runtime
- freellmapi remains the sole external LLM endpoint
- `claude_code_executor.py` and `code_generator.py` can be kept as dead code or removed — do not break imports if other code references them
- `max_turns=30` hard cap prevents runaway agentic loops
- LiteLLM image must be pinned `>=1.82.9` (security — 1.82.7/1.82.8 had malware incident)

---

## Acceptance Criteria

- `docker-compose up` starts litellm service cleanly alongside freellmapi
- Dev pipeline for a simple text-change story produces a PR with only the minimal line changed
- Dev pipeline for a multi-file feature story explores the codebase and modifies the correct files
- No `ANTHROPIC_API_KEY` env var is required for any of this to work
