---
phase: 22-agentic-codegen
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docker-compose.yml
  - litellm/config.yaml
  - backend/services/agentic_coder.py
  - backend/services/dev_pipeline.py
  - backend/requirements.txt
  - .env.example
autonomous: true
requirements:
  - REQ-22-01
  - REQ-22-02
  - REQ-22-03
  - REQ-22-04
  - REQ-22-05
  - REQ-22-06
  - REQ-22-07

must_haves:
  truths:
    - "docker-compose up starts a litellm service that listens on port 4000"
    - "dev pipeline invokes run_agentic_codegen() — no if/else CLAUDE_API_KEY branch"
    - "the agent writes files directly into workspace_path; git diff detects them as FileChange objects"
    - "no ANTHROPIC_API_KEY is required at runtime; ANTHROPIC_AUTH_TOKEN=sk-litellm-local suffices"
    - "execution order is preserved: clone → agentic_codegen → PR"
  artifacts:
    - path: "litellm/config.yaml"
      provides: "Model routing: sonnet → llama-3.3-70b-versatile (primary) + gemini-2.0-flash (failover)"
      contains: "model_name: sonnet"
    - path: "backend/services/agentic_coder.py"
      provides: "run_agentic_codegen() coroutine returning list[FileChange]"
      exports: ["run_agentic_codegen", "FileChange"]
    - path: "docker-compose.yml"
      provides: "litellm service block"
      contains: "litellm"
  key_links:
    - from: "backend/services/dev_pipeline.py"
      to: "backend/services/agentic_coder.py"
      via: "from services.agentic_coder import run_agentic_codegen"
      pattern: "run_agentic_codegen"
    - from: "backend services (docker)"
      to: "litellm (docker)"
      via: "ANTHROPIC_BASE_URL=http://litellm:4000 in agentic_coder env dict"
      pattern: "http://litellm:4000"
    - from: "litellm (docker)"
      to: "freellmapi (docker)"
      via: "api_base: http://freellmapi:3001/v1 in litellm/config.yaml"
      pattern: "freellmapi:3001"
---

<objective>
Replace the freellmapi one-shot text-completion codegen path with a fully agentic coding loop.
The Claude Agent SDK runs embedded inside the FastAPI backend, routing through a LiteLLM proxy
(which translates Anthropic /v1/messages → OpenAI /chat/completions) and onto freellmapi,
which handles actual LLM inference via Groq/Gemini/Cerebras/Mistral — no Anthropic API key required.

Purpose: The dev pipeline can now handle any story complexity (1-line fixes to multi-file features)
because the agent reads the repo, plans changes, and writes files in a real loop rather than
a single prompt-completion pass.

Output:
- litellm/config.yaml (model routing config)
- docker-compose.yml updated with litellm service
- backend/services/agentic_coder.py (new agentic codegen service)
- backend/services/dev_pipeline.py updated (single call replaces if/else)
- backend/requirements.txt updated (claude-agent-sdk added)
- .env.example updated (LITELLM_MASTER_KEY documented)

References: REQ-22-01, REQ-22-02, REQ-22-03, REQ-22-04, REQ-22-05, REQ-22-06, REQ-22-07
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@backend/services/dev_pipeline.py
@backend/services/pr_creator.py
@backend/services/repo_clone.py
@docker-compose.yml
@backend/requirements.txt
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add litellm service to docker-compose.yml and create litellm/config.yaml</name>
  <files>docker-compose.yml, litellm/config.yaml</files>
  <action>
Two edits in this task — config file first, then docker-compose.

**1a. Create litellm/config.yaml**

Create the directory and file at the repo root: `litellm/config.yaml`

Content to write verbatim:

```
model_list:
  - model_name: sonnet
    litellm_params:
      model: openai/llama-3.3-70b-versatile
      api_base: http://freellmapi:3001/v1
      api_key: dummy
  - model_name: sonnet
    litellm_params:
      model: openai/gemini-2.0-flash
      api_base: http://freellmapi:3001/v1
      api_key: dummy

general_settings:
  master_key: "sk-litellm-local"
```

The two `model_name: sonnet` entries give LiteLLM a primary (llama-3.3-70b-versatile — best free tool-use) and failover (gemini-2.0-flash — large context). Both route to freellmapi at http://freellmapi:3001/v1. The `api_key: dummy` satisfies LiteLLM's required field without forwarding a real key (per REQ-22-02).

**1b. Edit docker-compose.yml — add litellm service block**

In `docker-compose.yml`, insert the litellm service block inside the `services:` section, directly after the `freellmapi:` service block and before the `hermes:` service block. The new block is:

```
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    ports:
      - "4000:4000"
    volumes:
      - ./litellm/config.yaml:/app/config.yaml:ro
    environment:
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:-sk-litellm-local}
    command: ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]
    depends_on:
      - freellmapi
    networks:
      - ai-sdlc-net
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4000/health"]
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 5
```

Image note: `ghcr.io/berriai/litellm:main-latest` resolves to the latest main build which is >=1.82.9. Versions 1.82.7 and 1.82.8 had a malware incident; main-latest moved past those. If the team prefers a pinned digest, they should verify the current SHA from the GHCR registry and pin accordingly (per REQ-22-01 security constraint).

Also add litellm to the `backend` service's `depends_on` list so the backend waits for the proxy before accepting requests. The existing `depends_on` block for backend is:
```
    depends_on:
      - hermes
```
Change it to:
```
    depends_on:
      - hermes
      - litellm
```
  </action>
  <verify>
    <automated>cd /home/deepu/thoughtminds_projects/ai-sdlc-jira && grep -c "litellm" docker-compose.yml && grep -c "model_name: sonnet" litellm/config.yaml && python3 -c "import yaml; yaml.safe_load(open('litellm/config.yaml'))" && echo "YAML valid"</automated>
  </verify>
  <done>
    - litellm/config.yaml exists with two model_name: sonnet entries pointing at freellmapi:3001/v1
    - docker-compose.yml contains a litellm service block with image ghcr.io/berriai/litellm:main-latest, port 4000, volume mount for config.yaml, and depends_on: freellmapi
    - backend service depends_on includes litellm
    - docker-compose config parses without error: `docker-compose config` exits 0 (per REQ-22-01, REQ-22-02)
  </done>
</task>

<task type="auto">
  <name>Task 2: Create backend/services/agentic_coder.py</name>
  <files>backend/services/agentic_coder.py</files>
  <action>
Create `backend/services/agentic_coder.py` implementing an async `run_agentic_codegen()` function that drives the Claude Agent SDK through LiteLLM → freellmapi.

This file also defines `FileChange` as a re-export-compatible dataclass so callers in dev_pipeline.py do not need to import it from code_generator.py. The existing tests that import `FileChange` from `services.code_generator` are unaffected because code_generator.py is not deleted.

**Function signature:**
```python
async def run_agentic_codegen(
    workspace_path: str,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    architecture_content: str,
    directory_tree: str,
) -> list[FileChange]:
```

**Implementation details:**

1. Import `from dataclasses import dataclass` and define:
   ```python
   @dataclass
   class FileChange:
       path: str
       content: str
   ```
   (Same shape as services.code_generator.FileChange — pr_creator accepts any object with .path and .content.)

2. Import `from claude_agent_sdk import query, ClaudeAgentOptions`.

3. Build task_prompt as a multi-line f-string containing:
   - Jira issue key, summary, and description
   - Architecture page content (truncated to 8000 chars with a note if truncated)
   - Directory tree (truncated to 4000 chars)
   - Explicit instruction: "Read the relevant files, make the minimal necessary code changes to implement this story, then stop. Only edit files that need to change. Do not add unnecessary comments."

4. Construct ClaudeAgentOptions:
   ```python
   options = ClaudeAgentOptions(
       cwd=workspace_path,
       permission_mode="acceptEdits",
       max_turns=30,
       model="sonnet",
       env={
           "ANTHROPIC_BASE_URL": "http://litellm:4000",
           "ANTHROPIC_AUTH_TOKEN": "sk-litellm-local",
           "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
       },
       allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
   )
   ```
   CRITICAL: Do NOT include ANTHROPIC_API_KEY in the env dict. If it is set, Claude Code tries to authenticate against real Anthropic and bypasses the proxy (per REQ-22-03 constraint).
   CRITICAL: CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 must be set — this strips `anthropic-beta:` request headers that cause HTTP 400 errors on Groq and Gemini endpoints (they do not implement Anthropic beta features).

5. Run the agent and drain messages:
   ```python
   async for message in query(prompt=task_prompt, options=options):
       logger.debug("agent message type=%s", getattr(message, "type", "unknown"))
   ```
   The agent writes files directly into workspace_path. No return value from the loop is needed.

6. Detect changed files using git diff against HEAD:
   Run `git diff --name-only HEAD` as a subprocess in workspace_path. Parse stdout line-by-line for changed file paths. Also run `git ls-files --others --exclude-standard` to catch untracked new files. Combine both lists (deduplicated).

7. For each changed path, read the file content from workspace_path and construct a FileChange object. Skip binary files (catch UnicodeDecodeError). Log a warning and skip files that no longer exist (agent may have deleted them).

8. If no files were changed, log a warning at WARNING level (not raise — the caller handles the empty list case with a Jira comment).

9. Return the list of FileChange objects.

**Security notes (carry forward from existing threat model):**
- task_prompt contains only issue_key/summary/description/architecture/directory_tree — no token values (mirrors T-06-01)
- subprocess.run for git diff uses list args, not shell=True
- File reads use relative paths resolved under workspace_path only

**Logger:** `logger = logging.getLogger(__name__)` at module level.
  </action>
  <verify>
    <automated>cd /home/deepu/thoughtminds_projects/ai-sdlc-jira/backend && python3 -c "import ast, sys; ast.parse(open('services/agentic_coder.py').read()); print('syntax OK')" && grep -c "run_agentic_codegen" services/agentic_coder.py && grep -c "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS" services/agentic_coder.py && grep -c "ANTHROPIC_BASE_URL" services/agentic_coder.py && echo "all checks passed"</automated>
  </verify>
  <done>
    - backend/services/agentic_coder.py exists and parses without syntax errors
    - Contains async def run_agentic_codegen() with the 6-argument signature
    - Contains FileChange dataclass with path and content fields
    - Sets ANTHROPIC_BASE_URL=http://litellm:4000 and CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 in env dict
    - Does not set ANTHROPIC_API_KEY in env dict
    - Uses git diff --name-only HEAD and git ls-files --others to detect written files
    - Returns list[FileChange] (per REQ-22-03, REQ-22-07)
  </done>
</task>

<task type="auto">
  <name>Task 3: Update dev_pipeline.py, requirements.txt, and .env.example</name>
  <files>backend/services/dev_pipeline.py, backend/requirements.txt, .env.example</files>
  <action>
Three file edits in this task.

**3a. Update backend/services/dev_pipeline.py**

The goal is to remove the if/else CLAUDE_API_KEY branch (lines ~229-245) and replace it with a single run_agentic_codegen() call.

Step 1 — Update the import block at the top. Replace:
```python
from services.claude_code_executor import run_claude_code_executor
from services.code_generator import generate_code_changes
```
with:
```python
from services.agentic_coder import run_agentic_codegen
```
Leave all other imports unchanged (graphify_service, repo_clone, pr_creator, etc. remain).

Step 2 — Replace the if/else codegen branch. The block to replace is (around line 229):
```python
        # Step 7: Generate code changes via Claude Code executor when
        # CLAUDE_API_KEY set, otherwise fall back to freellmapi.
        if os.environ.get("CLAUDE_API_KEY"):
            file_changes = run_claude_code_executor(
                cloned.workspace_path,
                issue_key,
                issue_summary,
                issue_description,
                architecture_content,
            )
        else:
            file_changes = generate_code_changes(
                issue_key,
                issue_summary,
                issue_description,
                architecture_content,
                directory_tree,
                relevant_file_contents=relevant_files,
            )
```
Replace with:
```python
        # Step 7: Run agentic codegen — Claude Agent SDK via LiteLLM proxy → freellmapi.
        # REQ-22-04: Single unified call; no CLAUDE_API_KEY branch needed.
        file_changes = await run_agentic_codegen(
            cloned.workspace_path,
            issue_key,
            issue_summary,
            issue_description,
            architecture_content,
            directory_tree,
        )
```

All surrounding logic (relevant_files read, empty file_changes guard, PR creation, comment posting) remains unchanged. The execution order is preserved: clone (Step 5) → agentic_codegen (Step 7) → PR (Step 8), per REQ-22-07.

**3b. Update backend/requirements.txt**

Append `claude-agent-sdk` on a new line at the end of the file. No version pin is specified — pip resolves latest stable. If a specific version is required later, pin via `claude-agent-sdk==X.Y.Z` (per REQ-22-05).

**3c. Update .env.example**

Find the section in `.env.example` that documents LLM-related variables. Append the following block after the existing freellmapi/LLM entries (or at the end of the file if no clear LLM section exists):

```
# LiteLLM proxy auth token — used as ANTHROPIC_AUTH_TOKEN by the Claude Agent SDK.
# Must match general_settings.master_key in litellm/config.yaml.
# Do NOT set CLAUDE_API_KEY or ANTHROPIC_API_KEY — they would bypass the proxy.
LITELLM_MASTER_KEY=sk-litellm-local
```

Per REQ-22-06 this documents the only new env var needed; no Anthropic API key is required.
  </action>
  <verify>
    <automated>cd /home/deepu/thoughtminds_projects/ai-sdlc-jira/backend && python3 -c "import ast; ast.parse(open('services/dev_pipeline.py').read()); print('syntax OK')" && grep -c "run_agentic_codegen" services/dev_pipeline.py && python3 -c "reqs=open('requirements.txt').read(); assert 'claude-agent-sdk' in reqs, 'missing'; print('requirements OK')" && echo "all checks passed"</automated>
  </verify>
  <done>
    - backend/services/dev_pipeline.py imports run_agentic_codegen from services.agentic_coder
    - dev_pipeline.py does not contain the string "CLAUDE_API_KEY" or calls to run_claude_code_executor / generate_code_changes (the branch is removed)
    - dev_pipeline.py calls await run_agentic_codegen(...) with 6 args matching the function signature
    - backend/requirements.txt contains claude-agent-sdk
    - .env.example contains LITELLM_MASTER_KEY=sk-litellm-local with explanatory comment
    - Python syntax check passes on dev_pipeline.py (per REQ-22-04, REQ-22-05, REQ-22-06)
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| backend → litellm | agentic_coder sends Anthropic-format messages; ANTHROPIC_AUTH_TOKEN must match litellm master_key |
| litellm → freellmapi | LiteLLM translates to OpenAI format; api_key: dummy must not leak real creds |
| agent → workspace_path | Claude Agent SDK writes arbitrary files; path must be scoped to temp workspace |
| github_token → PR creation | Token embedded in push URL; must not appear in logs |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-22-01 | Spoofing | litellm master_key | mitigate | LITELLM_MASTER_KEY injected as env var from .env; not hardcoded in image; config.yaml uses "sk-litellm-local" default matching backend env |
| T-22-02 | Tampering | agent writes to workspace | mitigate | Agent cwd=workspace_path (tempdir); pr_creator already path-traversal-checks each FileChange.path via resolve() against workspace_root (T-15-06) |
| T-22-03 | Repudiation | agent actions untracked | accept | git diff --name-only HEAD provides an audit trail of what the agent changed; PR diff visible on GitHub |
| T-22-04 | Information Disclosure | task_prompt content | mitigate | Prompt contains only issue_key/summary/description/architecture/directory_tree — no token values interpolated (mirrors T-06-01) |
| T-22-05 | Denial of Service | agent runaway loop | mitigate | max_turns=30 hard cap in ClaudeAgentOptions prevents infinite loops |
| T-22-06 | Elevation of Privilege | ANTHROPIC_API_KEY env leakage | mitigate | agentic_coder.py must NOT set ANTHROPIC_API_KEY in options.env — documented as CRITICAL in action block; if set, agent bypasses proxy and hits real Anthropic endpoint |
| T-22-SC | Tampering | ghcr.io/berriai/litellm image supply chain | mitigate | Pin to main-latest (>=1.82.9); 1.82.7/1.82.8 had confirmed malware incident; team should verify digest if stricter supply-chain policy required |
</threat_model>

<verification>
After all three tasks complete, run end-to-end structural checks:

```bash
# 1. docker-compose config parses cleanly
cd /home/deepu/thoughtminds_projects/ai-sdlc-jira && docker-compose config > /dev/null && echo "compose OK"

# 2. litellm config is valid YAML with required keys
python3 -c "
import yaml
cfg = yaml.safe_load(open('litellm/config.yaml'))
models = cfg['model_list']
assert len(models) == 2, 'expected 2 model entries'
assert all(m['model_name'] == 'sonnet' for m in models)
assert all('freellmapi:3001' in m['litellm_params']['api_base'] for m in models)
print('litellm config OK')
"

# 3. agentic_coder module loads (syntax check)
cd backend && python3 -c "import ast; ast.parse(open('services/agentic_coder.py').read()); print('agentic_coder syntax OK')"

# 4. dev_pipeline no longer references old codegen imports
python3 -c "
src = open('services/dev_pipeline.py').read()
assert 'run_claude_code_executor' not in src, 'old executor import still present'
assert 'generate_code_changes' not in src, 'old generator import still present'
assert 'run_agentic_codegen' in src, 'new function not wired'
print('dev_pipeline imports OK')
"

# 5. requirements has new dep
python3 -c "assert 'claude-agent-sdk' in open('requirements.txt').read(); print('requirements OK')"
```
</verification>

<success_criteria>
- `docker-compose config` exits 0 with litellm service listed
- litellm/config.yaml has two `model_name: sonnet` entries routing to freellmapi:3001/v1
- backend/services/agentic_coder.py defines FileChange and run_agentic_codegen() with correct env dict (ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS; no ANTHROPIC_API_KEY)
- backend/services/dev_pipeline.py has a single `await run_agentic_codegen(...)` call replacing the old if/else branch; Python syntax check passes
- backend/requirements.txt contains claude-agent-sdk
- .env.example documents LITELLM_MASTER_KEY
- Execution order contract: clone → agentic_codegen → PR (unchanged surrounding logic in dev_pipeline.py)
</success_criteria>

<output>
Create `.planning/phases/22-agentic-codegen/22-01-SUMMARY.md` when done.
</output>
