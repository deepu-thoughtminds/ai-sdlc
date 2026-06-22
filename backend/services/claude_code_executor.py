"""Claude Code executor — runs claude CLI as a subprocess in the cloned workspace.

When CLAUDE_API_KEY is set, dev_pipeline uses this module instead of
generate_code_changes so that the full Claude Code agentic loop (including
/graphify, /gsd-graphify, and /gsd-quick skills) runs against the real repo.

The executor:
  1. Builds a prompt that instructs claude to update the graphify index,
     plan via /gsd-graphify, and implement via /gsd-quick.
  2. Runs `claude --dangerously-skip-permissions -p <prompt>` in workspace_path.
     --dangerously-skip-permissions is required for non-interactive subprocess
     invocation — the user has explicitly authorised this usage.
  3. Reads the git diff afterward to discover changed + new files.
  4. Returns them as FileChange objects so the rest of dev_pipeline (PR creation,
     cleanup) continues unchanged.
"""

import logging
import os
import subprocess

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
        "Steps:\n"
        "1. Run /graphify update . to update the codebase index\n"
        "2. Run /gsd-graphify plan to plan the implementation\n"
        "3. Run /gsd-quick implement the story based on the plan\n"
        "Make all necessary code changes to implement the story."
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
