"""Agentic coder — runs OpenCode CLI (opencode run) against a cloned workspace.

Replaces the claude_agent_sdk harness. OpenCode supports any OpenAI-compatible
model; we route to opencode/deepseek-v4-flash-free via the opencode.ai Zen
provider. File changes are discovered afterward via git diff, same as before.
"""

import asyncio
import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_ARCHITECTURE_CHARS = 8000
_MAX_DIRECTORY_TREE_CHARS = 4000
_MAX_EVENT_CHARS = 2000
_OPENCODE_TIMEOUT = 600  # 10 min

# Callback: (event_type, content, tool_name, detail)
OnEvent = Callable[[str, str, str | None, str | None], None]


@dataclass
class FileChange:
    path: str
    content: str


def _build_task_prompt(
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    architecture_content: str,
    directory_tree: str,
) -> str:
    return (
        "You are a senior software engineer implementing a Jira story directly "
        "in this repository. Make the MINIMUM necessary changes to implement "
        "the following story.\n\n"
        f"Jira Ticket: {issue_key}\n"
        f"Summary: {issue_summary}\n"
        f"Description:\n{issue_description}\n\n"
        "Architecture Design:\n"
        f"{architecture_content[:_MAX_ARCHITECTURE_CHARS]}\n\n"
        "Existing Codebase Structure:\n"
        f"{directory_tree[:_MAX_DIRECTORY_TREE_CHARS]}\n\n"
        "CRITICAL RULES:\n"
        "- Make MINIMAL, TARGETED changes. Only modify the specific lines needed.\n"
        "- NEVER rewrite an entire file when a small edit will do.\n"
        "- Minimise the number of files changed.\n"
        "- Do not add or modify test files unless the story explicitly requires it.\n"
        "- Write your changes directly to the files in this workspace — do not just describe them.\n"
    )


def _opencode_config() -> str:
    """Inline JSON config passed via OPENCODE_CONFIG_CONTENT."""
    api_key = os.environ.get("OPENCODE_API_KEY", "")
    return json.dumps({
        "provider": {
            "opencode": {
                "options": {"apiKey": api_key}
            }
        }
    })


def _parse_json_events(line: str, on_event: OnEvent) -> None:
    """Best-effort parse of a --format json event line into on_event calls."""
    try:
        ev = json.loads(line)
        kind = ev.get("type", "")
        if kind == "assistant":
            for part in ev.get("content", []):
                if part.get("type") == "text":
                    text = (part.get("text") or "").strip()
                    if text:
                        on_event("thinking", text[:_MAX_EVENT_CHARS], None, None)
                elif part.get("type") == "tool-call":
                    tool = part.get("toolName") or "tool"
                    args = part.get("args") or {}
                    detail = next(
                        (str(v)[:_MAX_EVENT_CHARS] for k, v in args.items()
                         if k in ("file_path", "path", "command", "pattern") and v),
                        None,
                    )
                    on_event("action", tool, tool, detail)
    except (json.JSONDecodeError, TypeError):
        pass


async def run_agentic_codegen(
    workspace_path: str,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    architecture_content: str,
    directory_tree: str,
    on_event: OnEvent | None = None,
) -> list[FileChange]:
    """Run OpenCode CLI against workspace_path and return changed FileChange list."""
    task_prompt = _build_task_prompt(
        issue_key, issue_summary, issue_description, architecture_content, directory_tree
    )

    model = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
    opencode_bin = os.environ.get("OPENCODE_BIN", "opencode")

    cmd = [
        opencode_bin, "run", task_prompt,
        "--model", model,
        "--dir", workspace_path,
        "--dangerously-skip-permissions",
        "--format", "json",
    ]

    env = {**os.environ, "OPENCODE_CONFIG_CONTENT": _opencode_config()}

    logger.info("Running agentic codegen for ticket %s in %s", issue_key, workspace_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_lines: list[str] = []
        # Stream stdout line-by-line for event callbacks
        async def _read_stdout() -> None:
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                stdout_lines.append(line)
                if on_event is not None:
                    _parse_json_events(line, on_event)

        await asyncio.wait_for(
            asyncio.gather(_read_stdout(), proc.wait()),
            timeout=_OPENCODE_TIMEOUT,
        )

        if proc.returncode != 0:
            logger.warning(
                "opencode exited %s for ticket %s", proc.returncode, issue_key
            )

    except asyncio.TimeoutError:
        logger.warning("opencode timed out after %ss for ticket %s", _OPENCODE_TIMEOUT, issue_key)
        try:
            proc.kill()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("opencode failed for ticket %s: %s", issue_key, exc)

    if on_event is not None:
        on_event("goal", "Code generation finished", None, None)

    file_changes = _collect_file_changes(workspace_path)
    if not file_changes:
        logger.warning("Agentic codegen produced no file changes for ticket %s", issue_key)
    return file_changes


def _collect_file_changes(workspace_path: str) -> list[FileChange]:
    """Return FileChange objects for files modified or added since HEAD."""
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
        except Exception as exc:
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
        len(file_changes), workspace_path,
    )
    return file_changes
