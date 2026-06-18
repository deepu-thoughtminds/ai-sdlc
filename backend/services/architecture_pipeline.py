"""Architecture pipeline service — ARCH-01, ARCH-02, ARCH-03.

Generates architecture options via freellmapi (Ollama /api/chat), creates drawio
diagrams for each option, publishes to Confluence, and stores draft in PipelineState
for architect review.

Pipeline flow:
  1. Build structured prompt with ticket info (issue_key, summary, description).
  2. Call route_request("architecture", prompt) — routes to Ollama via HEAVY_STAGES.
  3. Parse LLM output into option dicts (name, description, components, trade_offs).
  4. Generate mxGraph XML diagram for each option via generate_diagram().
  5. Publish all options + diagrams to Confluence via publish_architecture().
  6. Compose Jira comment text (options + optional Confluence URL).
  7. Persist PipelineState(stage="architecture", status="awaiting_approval").
  8. Return comment_text.

Threat mitigations:
  T-04-01: prompt contains only issue_key/summary/description — no token values
           are ever interpolated into the LLM prompt.
  T-04-03: Confluence publish failure is caught and degraded (page_url = "");
           pipeline continues and posts Jira comment without URL.
  T-04-07: LLM output embedded inside <pre> tags in Confluence body_html —
           not rendered as executable HTML/JS.
"""

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from services.confluence_client import publish_architecture
from services.drawio_service import generate_diagram
from services.llm_router import route_request

logger = logging.getLogger(__name__)


def _build_prompt(issue_key: str, summary: str, description: str) -> str:
    """Build the LLM prompt for architecture option generation.

    Asks for exactly 2-3 numbered architecture options in a structured format
    the parser can reliably extract.

    T-04-01: prompt contains only issue_key, summary, description — no token values.

    Args:
        issue_key: Jira issue key (e.g. "PROJ-1").
        summary: Issue summary/title field.
        description: Issue description field (plain text).

    Returns:
        A string prompt ready for route_request("architecture", ...).
    """
    return (
        f"You are a software architect. Analyze the following Jira ticket and propose "
        f"2-3 distinct architecture options.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {summary}\n"
        f"Description: {description}\n\n"
        f"For each option, output a section in exactly this format:\n\n"
        f"## Option [N]: [Name]\n"
        f"Description: [1-2 sentence description]\n"
        f"Components: [comma-separated list of component names]\n"
        f"Trade-offs: [bullet list of pros and cons]\n\n"
        f"Be concise. Focus on technical architecture decisions."
    )


def _parse_options(llm_output: str) -> list[dict[str, Any]]:
    """Parse LLM output into a list of architecture option dicts.

    Each dict has keys: name (str), description (str), components (list[str]),
    trade_offs (str).

    Parsing strategy: split on lines starting with '## Option'. For each section,
    extract name from the heading, Components line (split on comma), Description
    line, and Trade-offs block. Falls back gracefully — if parsing fails, returns
    a single option with the full LLM output as description and an empty
    components list.

    Args:
        llm_output: Raw LLM response text.

    Returns:
        Non-empty list of option dicts.
    """
    options: list[dict[str, Any]] = []
    # Split on option headings (## Option N: Name)
    sections = re.split(r'\n(?=## Option)', llm_output.strip())
    for section in sections:
        section = section.strip()
        if not section.startswith("## Option"):
            continue
        lines = section.split("\n")
        # First line: "## Option N: Name"
        heading = lines[0].replace("##", "").strip()
        # Remove "Option N: " prefix to get the option name
        name_match = re.match(r"Option\s+\d+:\s*(.*)", heading)
        name = name_match.group(1).strip() if name_match else heading

        description = ""
        components: list[str] = []
        trade_offs_lines: list[str] = []
        in_tradeoffs = False

        for line in lines[1:]:
            if line.startswith("Description:"):
                description = line.replace("Description:", "").strip()
                in_tradeoffs = False
            elif line.startswith("Components:"):
                raw_comps = line.replace("Components:", "").strip()
                components = [c.strip() for c in raw_comps.split(",") if c.strip()]
                in_tradeoffs = False
            elif line.startswith("Trade-offs:"):
                in_tradeoffs = True
                rest = line.replace("Trade-offs:", "").strip()
                if rest:
                    trade_offs_lines.append(rest)
            elif in_tradeoffs and line.strip():
                trade_offs_lines.append(line.strip())

        options.append({
            "name": name,
            "description": description,
            "components": components,
            "trade_offs": "\n".join(trade_offs_lines),
        })

    if not options:
        # Fallback: treat entire output as one option so pipeline never fails
        options = [{
            "name": "Architecture Proposal",
            "description": llm_output[:500],
            "components": [],
            "trade_offs": "",
        }]

    return options


async def run(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    db: Session,
) -> str:
    """Run the full architecture pipeline for a ticket.

    Steps:
    1. Build prompt and call route_request("architecture", prompt) — routes to Ollama.
    2. Parse LLM output into architecture options.
    3. For each option: call generate_diagram(name, components, connections=[]).
    4. Call publish_architecture(project, issue_key, full_text, diagram_xmls) — returns URL or "".
    5. Compose final comment text: options + Confluence URL (if available).
    6. Create PipelineState(stage="architecture", status="awaiting_approval", draft_content=comment_text).
    7. Return comment_text.

    T-04-01: prompt contains only issue_key, summary, description — no token values.
    T-04-03: Confluence publish failure is caught and degraded; pipeline continues.

    Args:
        project: Project ORM with jira_url, confluence_url, encrypted tokens.
        issue_key: Jira issue key (e.g. "PROJ-1").
        issue_summary: Issue summary field.
        issue_description: Issue description field (plain text).
        db: SQLAlchemy session for PipelineState persistence.

    Returns:
        Full architecture comment text (options + optional Confluence URL).
    """
    logger.info("Architecture pipeline started for ticket %s", issue_key)

    # Step 1: Generate architecture options via LLM
    # T-04-01: prompt contains only issue_key/summary/description — no token values
    prompt = _build_prompt(issue_key, issue_summary, issue_description)
    route_result = route_request("architecture", prompt)
    llm_output = route_result.content

    # Step 2: Parse options from LLM output
    options = _parse_options(llm_output)

    # Step 3: Generate drawio diagrams for each option
    # connections=[] for MVP — component relationships not parsed from LLM output
    diagram_xmls: list[str] = []
    for opt in options:
        xml = generate_diagram(opt["name"], opt["components"], [])
        diagram_xmls.append(xml)

    # Step 4: Build full architecture text for comment and Confluence
    options_text = "\n\n".join(
        f"*Option {i + 1}: {opt['name']}*\n"
        f"{opt['description']}\n"
        f"Components: {', '.join(opt['components']) if opt['components'] else 'N/A'}\n"
        f"Trade-offs:\n{opt['trade_offs']}"
        for i, opt in enumerate(options)
    )

    # Step 5: Publish to Confluence (graceful degradation on any failure)
    # T-04-03: all exceptions caught here; pipeline continues without URL
    try:
        page_url = await publish_architecture(
            project, issue_key, options_text, diagram_xmls
        )
    except Exception as exc:
        logger.warning(
            "Confluence publishing failed for ticket %s: %s", issue_key, exc
        )
        page_url = ""

    # Step 6: Compose comment text
    confluence_suffix = (
        f"\n\nFull architecture document (with diagrams): {page_url}"
        if page_url
        else "\n\n(Confluence publishing unavailable — diagrams not attached)"
    )
    comment_text = (
        f"*Architecture Options for {issue_key}*\n\n"
        f"{options_text}"
        f"{confluence_suffix}\n\n"
        "Reply with 'approved [option name]' or 'approved @developer-name' to select "
        "an option and assign to a developer."
    )

    # Step 7: Persist PipelineState for architect approval workflow
    state_row = PipelineState(
        project_id=project.id,
        ticket_key=issue_key,
        stage="architecture",
        status="awaiting_approval",
        draft_content=comment_text,
    )
    db.add(state_row)
    db.commit()

    logger.info(
        "Architecture pipeline complete for ticket %s — awaiting approval", issue_key
    )
    return comment_text
