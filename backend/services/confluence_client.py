"""Async Confluence REST API client.

Publishes architecture pages to Confluence Cloud.
Auth: Basic auth with ('', confluence_token) — Confluence Cloud API tokens do not
require an email prefix for token-only auth.

Threat mitigations:
  T-04-02: confluence_token decrypted at call time via decrypt_credential; never
           passed to logger; _auth_header built and held in memory only.
  T-04-03: timeout=30.0s on AsyncClient; all exceptions caught in publish_architecture
           returning "" (no crash).
  T-04-05: confluence_token is decrypted at runtime; never logged.
  T-04-06: Basic auth uses ('', token) — Confluence API token auth pattern;
           base64 encoding is standard; no email required for token-only API access.
"""

import base64
import html
import logging
from typing import Any

import httpx

from models.project import Project
from services.crypto import decrypt_credential

logger = logging.getLogger(__name__)


class ConfluenceClient:
    """Async Confluence REST API client.

    Uses httpx.AsyncClient for all HTTP calls. Instantiated with a decrypted
    token — the caller is responsible for decrypting before construction.

    Args:
        base_url: Confluence instance base URL (e.g. "https://org.atlassian.net").
        token: Decrypted Confluence API token (plaintext). T-04-02: never logged.
    """

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        # T-04-02 / T-04-06: Basic auth with empty username for API token
        # Never log the token value.
        raw = f":{token}".encode()
        self._auth_header = "Basic " + base64.b64encode(raw).decode()

    def _headers(self) -> dict[str, str]:
        """Return standard Confluence API request headers including auth."""
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def create_page(
        self,
        space_key: str,
        title: str,
        body_html: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /wiki/rest/api/content — create a new Confluence page.

        Args:
            space_key: Confluence space key (e.g. "PROJ").
            title: Page title.
            body_html: HTML content for the page body (storage format).
            parent_id: Optional parent page ID for nesting.

        Returns:
            Response dict from Confluence API (includes 'id' and '_links').

        Raises:
            httpx.HTTPStatusError: on non-2xx response.
        """
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/wiki/rest/api/content",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def find_page(self, space_key: str, title: str) -> dict[str, Any] | None:
        """GET /wiki/rest/api/content/search — find an existing page by exact title.

        Uses a CQL query scoped to space_key + title + type=page, with
        expand=version so the caller can read the current version number
        without a second request. limit=1 bounds the response (T-12-04).

        Args:
            space_key: Confluence space key.
            title: Exact page title to search for.

        Returns:
            The first matching result dict (includes "id" and "version.number")
            if found, else None.

        Raises:
            httpx.HTTPStatusError: on non-2xx response (caller wraps in try/except).
        """
        cql = f'space="{space_key}" AND title="{title}" AND type=page'
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/wiki/rest/api/content/search",
                headers=self._headers(),
                params={"cql": cql, "limit": 1, "expand": "version"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                return results[0]
            return None

    async def update_page(
        self,
        page_id: str,
        space_key: str,
        title: str,
        body_html: str,
        version: int,
    ) -> dict[str, Any]:
        """PUT /wiki/rest/api/content/{page_id} — update an existing page in place.

        Args:
            page_id: Confluence page id to update.
            space_key: Confluence space key.
            title: Page title.
            body_html: New HTML content for the page body (storage format).
            version: New version number (must be current version + 1).

        Returns:
            Response dict from Confluence API.

        Raises:
            httpx.HTTPStatusError: on non-2xx response.
        """
        payload: dict[str, Any] = {
            "id": page_id,
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
            "version": {"number": version},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{self.base_url}/wiki/rest/api/content/{page_id}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def get_page_url(self, space_key: str, page_id: str) -> str:
        """Construct the Confluence page URL from base_url, space_key, and page_id.

        Does not make a network call — pure URL construction.

        Args:
            space_key: Confluence space key.
            page_id: The Confluence page id string.

        Returns:
            Full URL to the Confluence page.
        """
        return f"{self.base_url}/wiki/spaces/{space_key}/pages/{page_id}"

    async def publish_architecture(
        self,
        project: Project,
        issue_key: str,
        summary: str,
        approach: str,
        key_decisions: str,
        risks: str,
        is_complex: bool = False,
        component_breakdown: str = "",
        integration_points: str = "",
        diagram_xml: str = "",
        viewer_url: str = "",
    ) -> str:
        """Render a structured architecture page and publish to Confluence (find-or-update).

        Branches between two HTML templates based on `is_complex`:
        - True: `_render_diagram_template` — six sections plus a drawio-xml block
          and a diagrams.net viewer link.
        - False: `_render_text_only_template` — four text-only sections.

        All LLM-generated text params are HTML-escaped via `_escape()` inside the
        template builders before interpolation (T-12-01).

        Searches for an existing page titled "Architecture: {issue_key}" via
        `find_page` before creating one; if found, updates in place (PUT) with
        the version incremented, avoiding duplicate pages on repeated publishes
        for the same issue_key.

        Space key: project.project_key (used as Confluence space key).

        T-04-03 / T-12-05: every exception from search/create/update is caught
        here and results in an empty string return — the caller's graceful
        degradation path (Jira comment without URL) keeps working unchanged.

        Args:
            project: Project ORM with confluence_url, confluence_token, project_key fields.
            issue_key: Jira issue key (e.g. "PROJ-1").
            summary: Architecture summary text (LLM-generated, escaped).
            approach: Architecture approach text (LLM-generated, escaped).
            key_decisions: Key decisions text (LLM-generated, escaped).
            risks: Risks text (LLM-generated, escaped).
            is_complex: If True, render the diagram+components template.
            component_breakdown: Component breakdown text (diagram template only).
            integration_points: Integration points text (diagram template only).
            diagram_xml: Raw mxGraph XML (diagram template only, not escaped).
            viewer_url: diagrams.net viewer URL (diagram template only, not escaped).

        Returns:
            The full page URL string on success.
            Empty string "" on any exception (graceful degradation — Jira comment
            still posts without URL).
        """
        try:
            title = f"Architecture: {issue_key}"
            space_key = project.project_key

            if is_complex:
                body_html = _render_diagram_template(
                    issue_key,
                    summary,
                    approach,
                    component_breakdown,
                    integration_points,
                    key_decisions,
                    risks,
                    diagram_xml,
                    viewer_url,
                )
            else:
                body_html = _render_text_only_template(
                    issue_key, summary, approach, key_decisions, risks
                )

            existing_page = await self.find_page(space_key, title)
            if existing_page is not None:
                existing_page_id = existing_page.get("id", "")
                current_version = existing_page.get("version", {}).get("number", 0)
                result = await self.update_page(
                    existing_page_id,
                    space_key,
                    title,
                    body_html,
                    version=current_version + 1,
                )
                page_id = existing_page_id
            else:
                result = await self.create_page(space_key, title, body_html)
                page_id = result.get("id", "")

            if not page_id:
                logger.warning(
                    "Confluence page published but no id returned for ticket %s", issue_key
                )
                return ""

            page_url = self.get_page_url(space_key, page_id)
            logger.info(
                "Architecture published to Confluence for ticket %s: %s",
                issue_key,
                page_url,
            )
            return page_url

        except Exception as exc:
            # T-04-03 / T-12-05: all exceptions caught; graceful degradation — never expose token
            logger.warning(
                "publish_architecture failed for ticket %s: %s — returning empty URL",
                issue_key,
                exc,
            )
            return ""


# ---------------------------------------------------------------------------
# Module-level HTML-escaping helper and template builders
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """HTML-escape text for safe interpolation into Confluence storage-format HTML.

    Single escaping entry point (T-12-01) — every piece of LLM-generated text
    must pass through this before being interpolated into a template string.
    Does NOT apply to raw mxGraph XML (pre-escaped by drawio_service._escape_xml)
    or viewer URLs (pre-encoded by drawio_service.generate_viewer_url).
    """
    return html.escape(text, quote=True)


def _render_text_only_template(
    issue_key: str,
    summary: str,
    approach: str,
    key_decisions: str,
    risks: str,
) -> str:
    """Render the text-only architecture page template (no diagram/components).

    Four sections in order: Summary, Approach, Key Decisions, Risks.
    All values pass through `_escape()` before interpolation.
    """
    return (
        f"<h1>Architecture: {issue_key}</h1>"
        f"<h2>Summary</h2><p>{_escape(summary)}</p>"
        f"<h2>Approach</h2><p>{_escape(approach)}</p>"
        f"<h2>Key Decisions</h2><p>{_escape(key_decisions)}</p>"
        f"<h2>Risks</h2><p>{_escape(risks)}</p>"
    )


def _render_diagram_template(
    issue_key: str,
    summary: str,
    approach: str,
    component_breakdown: str,
    integration_points: str,
    key_decisions: str,
    risks: str,
    diagram_xml: str,
    viewer_url: str,
) -> str:
    """Render the diagram+components architecture page template.

    Six sections in order: Summary, Approach, Component Breakdown,
    Integration Points, Key Decisions, Risks — all escaped via `_escape()` —
    followed by a Diagram section containing the raw mxGraph XML in a
    <pre class="drawio-xml"> block (NOT escaped — see T-12-02) and a link to
    the diagrams.net viewer (viewer_url interpolated raw — pre-encoded,
    trusted internal source).
    """
    return (
        f"<h1>Architecture: {issue_key}</h1>"
        f"<h2>Summary</h2><p>{_escape(summary)}</p>"
        f"<h2>Approach</h2><p>{_escape(approach)}</p>"
        f"<h2>Component Breakdown</h2><p>{_escape(component_breakdown)}</p>"
        f"<h2>Integration Points</h2><p>{_escape(integration_points)}</p>"
        f"<h2>Key Decisions</h2><p>{_escape(key_decisions)}</p>"
        f"<h2>Risks</h2><p>{_escape(risks)}</p>"
        f"<h2>Diagram</h2>"
        f'<pre class="drawio-xml">{diagram_xml}</pre>'
        f'<p><a href="{viewer_url}">Open diagram in diagrams.net</a></p>'
    )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


async def publish_architecture(
    project: Project,
    issue_key: str,
    summary: str,
    approach: str,
    key_decisions: str,
    risks: str,
    is_complex: bool = False,
    component_breakdown: str = "",
    integration_points: str = "",
    diagram_xml: str = "",
    viewer_url: str = "",
) -> str:
    """Module-level convenience wrapper for ConfluenceClient.publish_architecture.

    Constructs a ConfluenceClient from project credentials and delegates to
    the instance method. Used by architecture_pipeline for direct import.

    Args:
        project: Project ORM with confluence_url, confluence_token, project_key.
        issue_key: Jira issue key.
        summary: Architecture summary text.
        approach: Architecture approach text.
        key_decisions: Key decisions text.
        risks: Risks text.
        is_complex: If True, render the diagram+components template.
        component_breakdown: Component breakdown text (diagram template only).
        integration_points: Integration points text (diagram template only).
        diagram_xml: Raw mxGraph XML (diagram template only).
        viewer_url: diagrams.net viewer URL (diagram template only).

    Returns:
        Page URL string on success; "" on any failure.
    """
    try:
        conf_token = decrypt_credential(project.confluence_token)
        client = ConfluenceClient(project.confluence_url, conf_token)
        return await client.publish_architecture(
            project,
            issue_key,
            summary,
            approach,
            key_decisions,
            risks,
            is_complex=is_complex,
            component_breakdown=component_breakdown,
            integration_points=integration_points,
            diagram_xml=diagram_xml,
            viewer_url=viewer_url,
        )
    except Exception as exc:
        logger.warning(
            "publish_architecture (module fn) failed for ticket %s: %s — returning empty URL",
            issue_key,
            exc,
        )
        return ""
