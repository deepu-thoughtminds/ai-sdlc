"""Claude Code executor — runs claude CLI as a subprocess in the cloned workspace.

When CLAUDE_API_KEY is set, dev_pipeline uses this module instead of
generate_code_changes so that the full Claude Code agentic loop (including
codebase-memory-mcp and /gsd-quick skills) runs against the real repo.

The executor:
  1. Builds a prompt that instructs claude to index the repo with
     codebase-memory-mcp (no LLM, static binary MCP server), query the
     resulting knowledge graph to understand relevant code, then implement
     via /gsd-quick.
  2. Runs `claude --dangerously-skip-permissions -p <prompt>` in workspace_path.
     --dangerously-skip-permissions is required for non-interactive subprocess
     invocation — the user has explicitly authorised this usage.
  3. Reads the git diff afterward to discover changed + new files.
  4. Returns them as FileChange objects so the rest of dev_pipeline (PR creation,
     cleanup) continues unchanged.

codebase-memory-mcp is installed in the container (backend/Dockerfile) and
registered as a stdio MCP server in /root/.claude/.mcp.json so the claude CLI
picks it up automatically without LLM involvement.
"""

import logging
import os
import subprocess

from claude_agent_sdk import ClaudeAgentOptions, query

from services.code_generator import FileChange

logger = logging.getLogger(__name__)


def run_claude_code_executor(
    workspace_path: str,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    architecture_content: str,
) -> list[FileChange]:
    """Run claude CLI in workspace_path and return the resulting FileChange list.

    Args:
        workspace_path:       Absolute path to the cloned repository workspace.
        issue_key:            Jira issue key (e.g. "PROJ-42").
        issue_summary:        Issue summary field.
        issue_description:    Issue description (plain text).
        architecture_content: Architecture page content from Confluence.

    Returns:
        List of FileChange instances derived from git diff after the claude run.
        Empty list if the claude CLI exits non-zero or produces no diff.
    """
    prompt = (
        f"You are implementing Jira story {issue_key}: {issue_summary}\n\n"
        f"Description:\n{issue_description}\n\n"
        f"Architecture:\n{architecture_content}\n\n"
        "CRITICAL RULES — read before doing anything:\n"
        "- Make MINIMAL, TARGETED changes. Only modify the specific lines needed for the story.\n"
        "- NEVER rewrite an entire file. Use the Edit tool to change only the affected lines.\n"
        "- NEVER change export styles (default vs named) — match what the file already uses.\n"
        "- NEVER change import names or atom names — use the exact names already in the file.\n"
        "- Do NOT run /gsd-quick or any other skill. Implement directly.\n\n"
        "Steps (execute in order):\n"
        "1. INDEX: Call codebase-memory-mcp `index_repository` with repo_path='.'\n"
        "2. FIND FILES: Call `search_graph` with a query describing the feature area "
        "(e.g. 'login page', 'auth') to identify which files to change\n"
        "3. READ EXACT CONTENT: For every file you plan to modify, call "
        "`get_code_snippet` with the qualified_name to get the full current source. "
        "You MUST read each file before touching it.\n"
        "4. FIND IMPORTERS: For every file you will modify, call `search_code` with "
        "the filename to find all files that import it. Check that your planned changes "
        "preserve the export style and names that those importers expect.\n"
        "5. MAKE TARGETED EDITS: Use the Edit tool with precise old_string/new_string to "
        "change ONLY the lines required by the story. Do not alter surrounding code.\n"
        "6. VERIFY: After editing, read back the changed file with Read to confirm "
        "the change is correct and no surrounding code was broken."
    )

    logger.info("Running claude Code executor for ticket %s in %s", issue_key, workspace_path)

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("claude CLI failed for %s: %s", issue_key, exc)
        return []

    if result.returncode != 0:
        logger.error(
            "claude CLI exited %d for %s: %s", result.returncode, issue_key, result.stderr
        )
        return []

    logger.info("claude CLI succeeded for %s — collecting diff", issue_key)
    return _collect_file_changes(workspace_path)


async def run_claude_playwright_generator(
    workspace_path: str,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    codebase_context: str | None,
    relevant_file_contents: dict[str, str],
) -> list[FileChange]:
    """Generate Python Playwright evaluation tests via Claude Agent SDK + LiteLLM proxy.

    Uses the same routing as agentic_coder.py (ANTHROPIC_BASE_URL → litellm:4000)
    so no Anthropic API key is needed. The agent writes test files directly into
    workspace_path/tests/playwright/; changed files are discovered via git diff.
    """
    file_blocks = "\n\n".join(
        f"### {path}\n{content}" for path, content in relevant_file_contents.items()
    ) if relevant_file_contents else ""

    issue_slug = issue_key.lower().replace("-", "_")
    target_file = f"tests/playwright/test_{issue_slug}.py"
    frontend_url = os.environ.get("PLAYWRIGHT_BASE_URL", "http://frontend:3000")

    prompt = (
        f"YOUR ONLY JOB: Create the file `{target_file}` containing Python Playwright "
        f"tests for Jira story {issue_key}: {issue_summary}\n\n"
        f"Description:\n{issue_description}\n\n"
        + (f"Codebase context:\n{codebase_context[:4000]}\n\n" if codebase_context else "")
        + (f"Relevant source files:\n{file_blocks[:6000]}\n\n" if file_blocks else "")
        + "MANDATORY STEPS — do these in order, nothing else:\n"
        f"1. Run: mkdir -p tests/playwright\n"
        f"2. Write the file `{target_file}` using the Write tool.\n"
        "   The file must contain at least one pytest function (name starts with test_).\n\n"
        "FILE TEMPLATE to use as a starting point:\n"
        "```python\n"
        "import os\n"
        "import pytest\n"
        "from playwright.sync_api import Page, expect\n\n"
        f"BASE_URL = os.environ.get('BASE_URL', '{frontend_url}')\n\n"
        f"def test_{issue_slug}_acceptance(page: Page):\n"
        "    page.goto(BASE_URL)\n"
        "    # TODO: add assertions based on the story acceptance criteria\n"
        "    expect(page).to_have_url(BASE_URL + '/')\n"
        "```\n\n"
        "HARD CONSTRAINTS:\n"
        f"- Write ONLY to `{target_file}`. Do NOT touch any other file.\n"
        "- Use Python + pytest-playwright ONLY (not TypeScript, not Jest).\n"
        "- Do NOT modify any existing files in the repo.\n"
        f"- Do NOT skip step 1 (mkdir) or step 2 (Write `{target_file}`).\n"
    )

    options = ClaudeAgentOptions(
        cwd=workspace_path,
        permission_mode="acceptEdits",
        max_turns=30,
        model="sonnet",
        env={
            "ANTHROPIC_BASE_URL": "http://litellm:4000",
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("LITELLM_MASTER_KEY", "sk-litellm-local"),
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        },
        allowed_tools=["Bash", "Write"],
    )

    logger.info("Running Claude Playwright generator for ticket %s via LiteLLM proxy", issue_key)

    try:
        async for _message in query(prompt=prompt, options=options):
            pass
    except Exception as exc:  # noqa: BLE001
        logger.error("Claude Playwright generator failed for %s: %s", issue_key, exc)
        return []

    # Collect only the specific target file the agent was instructed to write.
    # Using git ls-files --others to find new untracked files (agent writes new files,
    # not modifying existing ones).
    all_changes = _collect_file_changes(workspace_path)
    pw_changes = [c for c in all_changes if c.path == target_file]
    if not pw_changes:
        # Fallback: accept any .py file under tests/playwright/ in case agent used a different name
        pw_changes = [c for c in all_changes if c.path.startswith("tests/playwright/") and c.path.endswith(".py")]
    if not pw_changes:
        logger.warning("Playwright generator produced no test files for ticket %s", issue_key)
    return pw_changes


def _collect_file_changes(workspace_path: str) -> list[FileChange]:
    """Return FileChange objects for files modified or added since HEAD.

    Combines:
      - `git diff --name-only HEAD` for modified tracked files
      - `git ls-files --others --exclude-standard` for new untracked files
    """
    changed: set[str] = set()

    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        try:
            out = subprocess.run(
                cmd, cwd=workspace_path, capture_output=True, text=True, timeout=30
            )
            if out.returncode == 0:
                changed.update(p.strip() for p in out.stdout.splitlines() if p.strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("git command %s failed: %s", cmd, exc)

    file_changes: list[FileChange] = []
    for rel_path in sorted(changed):
        abs_path = os.path.join(workspace_path, rel_path)
        try:
            with open(abs_path, encoding="utf-8") as fh:
                content = fh.read()
            file_changes.append(FileChange(path=rel_path, content=content))
            logger.info("Collected file change: %s", rel_path)
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Skipping unreadable file %s: %s", rel_path, exc)

    logger.info(
        "claude Code executor collected %d file change(s) for workspace %s",
        len(file_changes),
        workspace_path,
    )
    return file_changes
