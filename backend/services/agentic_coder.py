"""Agentic coder service — DEVPIPE-03 (Phase 22 replacement).

Runs the Claude Agent SDK against a cloned repository workspace, routed
through the local LiteLLM proxy (which forwards to freellmapi), so the dev
pipeline can handle story complexity ranging from single-line text changes
to multi-file architectural features without an Anthropic API subscription.

Unlike the old one-shot `generate_code_changes()` flow, the agent reads,
plans, and writes files directly into `workspace_path` using its own tool
loop (Read/Write/Bash/Glob/Grep). Changed files are discovered afterward via
`git diff` / `git ls-files`, the same technique used by
`claude_code_executor.py`.

Threat mitigation: `ANTHROPIC_API_KEY` must NEVER be set in this module's
env — if it were, the Claude Agent SDK would route directly to the real
Anthropic API (bypassing the LiteLLM proxy), incurring real API costs and
likely failing outright since no Anthropic key is provisioned for this
deployment. Only `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` are set, both
pointed at the local `litellm` service.
"""

import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    query,
)

logger = logging.getLogger(__name__)

_MAX_ARCHITECTURE_CHARS = 8000
_MAX_DIRECTORY_TREE_CHARS = 4000

# Cap captured reasoning/action text so a single agent_events document stays small.
_MAX_EVENT_CHARS = 2000

# Callback invoked for each captured agent event: (event_type, content, tool_name, detail).
# event_type is one of "thinking" | "action" | "goal".
OnEvent = Callable[[str, str, str | None, str | None], None]


@dataclass
class FileChange:
    """A single file-level code change discovered after the agent run.

    Fields:
        path:    Relative file path within the repository (e.g. "backend/main.py").
        content: Full file content read from disk after the agent finished.
    """

    path: str
    content: str


def _build_task_prompt(
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    architecture_content: str,
    directory_tree: str,
) -> str:
    """Build the agentic coding task prompt from issue + codebase context.

    Truncates architecture_content to _MAX_ARCHITECTURE_CHARS and
    directory_tree to _MAX_DIRECTORY_TREE_CHARS to keep the prompt within a
    reasonable token budget for the underlying free-tier models.
    """
    architecture_section = architecture_content[:_MAX_ARCHITECTURE_CHARS]
    directory_tree_section = directory_tree[:_MAX_DIRECTORY_TREE_CHARS]

    return (
        "You are a senior software engineer implementing a Jira story directly "
        "in this repository. Make the MINIMUM necessary changes to implement "
        "the following story.\n\n"
        f"Jira Ticket: {issue_key}\n"
        f"Summary: {issue_summary}\n"
        f"Description:\n{issue_description}\n\n"
        "Architecture Design:\n"
        f"{architecture_section}\n\n"
        "Existing Codebase Structure:\n"
        f"{directory_tree_section}\n\n"
        "CRITICAL RULES — read before doing anything:\n"
        "- Make MINIMAL, TARGETED changes. Only modify the specific lines needed "
        "for the story.\n"
        "- NEVER rewrite an entire file when a small edit will do. Read the file "
        "first, then change only the affected lines.\n"
        "- Minimise the number of files changed. Only touch a file if it MUST "
        "change to satisfy the story.\n"
        "- Do not add or modify test files unless the story explicitly requires "
        "new test logic.\n"
        "- For text/string changes: change ONLY that string and nothing else in "
        "the file.\n"
        "- Use the Read tool to inspect existing files before editing them so you "
        "match existing conventions, export styles, and naming.\n"
        "- Write your changes directly to the files in this workspace using the "
        "Write tool (or by editing existing files) — do not just describe the "
        "changes.\n"
    )


def _summarize_tool_input(tool_input: object) -> str | None:
    """Build a short, non-sensitive summary of a tool-use input for an action event.

    Surfaces the most useful identifier per tool (file path, command, pattern)
    without dumping full file contents. Returns None when nothing useful is found.
    """
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "command", "pattern", "query", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value[:_MAX_EVENT_CHARS]
    return None


def _emit_message_events(message: object, on_event: OnEvent) -> None:
    """Translate one Claude Agent SDK message into agent events via on_event.

    Defensive by design — any unexpected message/block shape is ignored rather
    than raised, so capturing reasoning can never break the codegen run.
    """
    try:
        if isinstance(message, AssistantMessage):
            for block in getattr(message, "content", []) or []:
                if isinstance(block, ThinkingBlock):
                    text = (getattr(block, "thinking", "") or "").strip()
                    if text:
                        on_event("thinking", text[:_MAX_EVENT_CHARS], None, None)
                elif isinstance(block, TextBlock):
                    text = (getattr(block, "text", "") or "").strip()
                    if text:
                        on_event("thinking", text[:_MAX_EVENT_CHARS], None, None)
                elif isinstance(block, ToolUseBlock):
                    tool_name = getattr(block, "name", None) or "tool"
                    detail = _summarize_tool_input(getattr(block, "input", None))
                    on_event("action", tool_name, tool_name, detail)
        elif isinstance(message, ResultMessage):
            num_turns = getattr(message, "num_turns", None)
            detail = f"{num_turns} turns" if num_turns is not None else None
            on_event("goal", "Code generation finished", None, detail)
    except Exception as exc:  # noqa: BLE001 — capturing reasoning must not break codegen
        logger.warning("Failed to capture agent event from message: %s", exc)


async def run_agentic_codegen(
    workspace_path: str,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    architecture_content: str,
    directory_tree: str,
    on_event: OnEvent | None = None,
) -> list[FileChange]:
    """Run the Claude Agent SDK against workspace_path and return FileChange list.

    Args:
        workspace_path:        Absolute path to the cloned repository workspace.
        issue_key:              Jira issue key (e.g. "PROJ-42").
        issue_summary:           Issue summary field.
        issue_description:       Issue description (plain text).
        architecture_content:    Architecture page content from Confluence
                                  (truncated to _MAX_ARCHITECTURE_CHARS).
        directory_tree:          Codebase directory tree summary (truncated to
                                  _MAX_DIRECTORY_TREE_CHARS).
        on_event:                Optional callback invoked for each captured agent
                                  event (thinking/action/goal) as the SDK streams
                                  messages, signature (event_type, content,
                                  tool_name, detail). Kept DB-free here: the caller
                                  supplies a closure that persists the event.

    Returns:
        List of FileChange instances derived from git diff/ls-files after the
        agent run. Empty list if no files changed — callers should treat this
        as a graceful "no changes" path rather than an error.
    """
    task_prompt = _build_task_prompt(
        issue_key, issue_summary, issue_description, architecture_content, directory_tree
    )

    # Threat mitigation: ANTHROPIC_API_KEY is intentionally NEVER set here —
    # doing so would bypass the LiteLLM proxy and route to the real Anthropic
    # API (cost + auth failure, since no Anthropic key is provisioned).
    options = ClaudeAgentOptions(
        cwd=workspace_path,
        permission_mode="acceptEdits",
        max_turns=60,
        model="sonnet",
        env={
            "ANTHROPIC_BASE_URL": "http://litellm:4000",
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("LITELLM_MASTER_KEY", "sk-litellm-local"),
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
            "CLAUDE_CODE_DISABLE_EXTENDED_THINKING": "1",
        },
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )

    logger.info("Running agentic codegen for ticket %s in %s", issue_key, workspace_path)

    async for message in query(prompt=task_prompt, options=options):
        if on_event is not None:
            _emit_message_events(message, on_event)

    file_changes = _collect_file_changes(workspace_path)
    if not file_changes:
        logger.warning("Agentic codegen produced no file changes for ticket %s", issue_key)
        return []

    return file_changes


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
        "Agentic codegen collected %d file change(s) for workspace %s",
        len(file_changes),
        workspace_path,
    )
    return file_changes
