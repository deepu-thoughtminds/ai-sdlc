"""Description elaboration pipeline — DESCCTX-01 + DESCCTX-02.

Implements the describe stage pipeline:
  1. (DESCCTX-01) Query codebase graph via cbm_call("search_graph", ...) for context
  2. Fetch active sprint backlog from Jira REST API via hermes_client
  3. Assemble a prompt combining ticket info + graph context + sprint context
  4. Run opencode CLI subprocess via _run_opencode_describe
  5. Return the generated description string

Uses codebase-memory-mcp graph for codebase context (replaces .hermes/codebase.md snapshot).

Threat mitigations:
  T-03-02: Prompt assembled inline — decrypted token is only used for hermes_client
           calls, not included in the prompt string; only issue_key is logged.
  T-03-06: post_sprint_backlog handles all errors and returns [].
  T-20-01: github_repo slug decrypted with decrypt_credential; decrypted value
           never logged — only issue_key is logged.
"""

import asyncio
import json
import logging
import os
import tempfile

from pymongo.database import Database

from models.project import Project
from services.agentic_coder import _opencode_config
from services.cbm_client import cbm_search_with_auto_index
from services.crypto import decrypt_credential
from services.hermes_client import post_sprint_backlog
from services.reasoning import REASONING_INSTRUCTION, split_reasoning
from services.ticket_tracking import safe_record_agent_event, safe_record_reasoning

logger = logging.getLogger(__name__)


async def _run_opencode_describe(prompt: str) -> tuple[str, str]:
    """Invoke opencode CLI for a text-generation prompt, with model fallback.

    Tries OPENCODE_MODEL first, then OPENCODE_FALLBACK_MODEL on empty result.
    Returns (content, "") — degrades to ("", "") if all models fail.
    """
    primary = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
    fallback = os.environ.get("OPENCODE_FALLBACK_MODEL", "opencode/mimo-v2.5-free")
    opencode_bin = os.environ.get("OPENCODE_BIN", "opencode")
    env = {**os.environ, "OPENCODE_CONFIG_CONTENT": _opencode_config(with_mcp=False)}

    for model in (primary, fallback):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                opencode_bin, "run", prompt,
                "--model", model,
                "--dir", tmpdir,
                "--dangerously-skip-permissions",
                "--format", "json",
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.warning("opencode CLI timed out for describe (model=%s)", model)
                continue
            except Exception as exc:
                logger.warning("opencode CLI failed for describe (model=%s): %s", model, exc)
                continue

            if proc.returncode != 0:
                logger.warning("opencode exited %s (model=%s): %s", proc.returncode, model, stderr_bytes.decode(errors="replace")[:500])
                continue

            text_parts: list[str] = []
            for line in stdout_bytes.decode(errors="replace").splitlines():
                try:
                    ev = json.loads(line)
                    if ev.get("type") == "text" and ev.get("part", {}).get("text"):
                        text_parts.append(ev["part"]["text"].strip())
                    elif ev.get("type") == "assistant":
                        for part in ev.get("content", []):
                            if part.get("type") == "text" and part.get("text"):
                                text_parts.append(part["text"].strip())
                except (json.JSONDecodeError, TypeError):
                    pass
            result = "\n\n".join(text_parts)
            if result:
                return result, ""
            logger.warning("opencode produced no text (model=%s); stderr: %s", model, stderr_bytes.decode(errors="replace")[:500])

    return "", ""


async def run(event: object, project: Project, db: Database) -> str:
    """Run the description elaboration pipeline for a Jira ticket.

    Steps:
    1. Decrypt project credentials and query codebase graph via CBM (DESCCTX-01).
    2. Fetch active sprint backlog (DESC-02) — graceful on error (returns []).
    3. Assemble a structured prompt with all available context.
    4. Call _run_opencode_describe(prompt) — opencode CLI subprocess.
    5. Return the generated description text.

    T-03-02: decrypted tokens used only for API calls, never included in prompt.

    Args:
        event: JiraCommentEvent (or compatible duck-typed object) with
               issue.key, issue.fields["summary"], and comment.body attributes.
        project: Project ORM object with jira_url, jira_token, github_url,
                 github_token, and project_key fields.

    Returns:
        The LLM-generated description string.
    """
    # --- Step 1 (DESCCTX-01): Query codebase graph via codebase-memory-mcp ---
    _issue_key_early = getattr(getattr(event, "issue", None), "key", "UNKNOWN")

    try:
        github_token = decrypt_credential(project.github_token) if project.github_token else ""
    except Exception as exc:
        logger.warning(
            "Failed to decrypt github_token for issue %s — graph query skipped: %s",
            _issue_key_early,
            exc,
        )
        github_token = ""

    # T-20-01: decrypt github_repo slug; decrypted value never logged
    try:
        github_repo = decrypt_credential(project.github_repo)
    except Exception as exc:
        logger.warning(
            "Failed to decrypt github_repo for issue %s — graph query skipped: %s",
            _issue_key_early,
            exc,
        )
        github_repo = ""

    # Ticket title needed for graph query — read early from event
    ticket_title = getattr(getattr(event, "issue", None), "summary", None) or _issue_key_early

    graph_text = "(codebase graph unavailable)"
    try:
        graph_result = await asyncio.to_thread(
            cbm_search_with_auto_index,
            ticket_title, 20, github_repo, github_token,
        )
        nodes = graph_result.get("nodes", graph_result.get("results", []))
        if nodes:
            graph_text = "\n".join(
                f"- {n.get('name', n.get('id', ''))} ({n.get('file', n.get('path', ''))})"
                for n in nodes[:20]
            )
        else:
            graph_text = "(no graph context available)"
    except Exception as exc:
        logger.warning("cbm search_graph failed for %s: %s", _issue_key_early, exc)
    codebase_text = graph_text

    # --- Step 2 (DESC-02): Fetch sprint backlog ---
    try:
        jira_token = decrypt_credential(project.jira_token)
    except Exception:
        jira_token = ""

    jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
    # T-03-06: all errors caught inside post_sprint_backlog; returns [] on failure
    backlog = await post_sprint_backlog(project.jira_url, jira_email, jira_token, project.project_key)

    # --- Step 3: Assemble prompt ---
    # Sprint context
    backlog_text = (
        "\n".join(f"- {i['key']}: {i['summary']} ({i['issue_type']})" for i in backlog)
        or "(no active sprint tickets)"
    )

    # Ticket info from the event
    issue_key = getattr(event.issue, "key", "UNKNOWN")  # type: ignore[union-attr]
    # Use .summary directly — JiraIssue now has summary as a top-level field
    # (flattened from issue.fields.summary in the webhook model validator)
    ticket_title = getattr(event.issue, "summary", None) or issue_key  # type: ignore[union-attr]
    # T-03-02: comment body from Jira; cap here as a defence-in-depth guard
    trigger_comment = (getattr(event.comment, "body", "") or "")[:4000]  # type: ignore[union-attr]

    prompt = (
        f"You are a senior product manager. Elaborate the following Jira ticket into a clear, "
        f"complete feature description.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {ticket_title}\n"
        f"Current description / trigger comment:\n{trigger_comment}\n\n"
        f"Sprint backlog context (related tickets in same sprint):\n{backlog_text}\n\n"
        f"Codebase context (module graph):\n{codebase_text}\n\n"
        f"Write an elaborated feature description (3-5 paragraphs) covering: user value, "
        f"acceptance criteria, technical scope, and any integration points visible in the "
        f"codebase. Reference specific module names and file paths from the codebase context "
        f"where relevant. Output only the description text."
        + REASONING_INSTRUCTION
    )

    # Record the context-gathering steps as agent actions (best-effort).
    safe_record_agent_event(
        db, project.id, issue_key, "description", "action", "Queried codebase graph",
        detail="graph context loaded" if graph_text != "(codebase graph unavailable)" else "no graph context",
    )
    safe_record_agent_event(
        db, project.id, issue_key, "description", "action", "Fetched sprint backlog",
        detail=f"{len(backlog)} ticket(s)",
    )

    # --- Step 4: Run opencode CLI ---
    logger.info("Running describe pipeline for issue %s", issue_key)
    content, _ = await _run_opencode_describe(prompt)
    if not content:
        logger.warning("describe_pipeline: opencode returned empty content for %s — aborting", issue_key)
        return ""

    # Split the model's <thinking> reasoning from the description it should post.
    reasoning, answer = split_reasoning(content)
    safe_record_reasoning(db, project.id, issue_key, "description", reasoning)
    safe_record_agent_event(
        db, project.id, issue_key, "description", "goal", "Description drafted",
    )

    return answer
