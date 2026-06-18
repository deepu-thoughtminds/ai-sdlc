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
        architecture_text: str,
        diagram_xmls: list[str],
    ) -> str:
        """Build an HTML page from architecture_text + diagram XMLs and publish to Confluence.

        HTML structure:
        - H1: "Architecture Options: {issue_key}"
        - architecture_text rendered in a <pre> block
        - Each diagram XML embedded in a <pre class="drawio-xml"> block (MVP: plain code blocks)

        Space key: project.project_key (used as Confluence space key).

        T-04-05: decrypt confluence_token at call time; never log the token value.

        Args:
            project: Project ORM with confluence_url, confluence_token, project_key fields.
            issue_key: Jira issue key (e.g. "PROJ-1").
            architecture_text: Full architecture options text.
            diagram_xmls: List of mxGraph XML strings (one per option).

        Returns:
            The full page URL string on success.
            Empty string "" on any exception (graceful degradation — Jira comment
            still posts without URL).
        """
        try:
            # T-04-05: decrypt at runtime; local var not logged
            conf_token = decrypt_credential(project.confluence_token)
            client = ConfluenceClient(project.confluence_url, conf_token)

            # Build HTML body
            diagrams_html = "".join(
                f'<h2>Diagram {i + 1}</h2><pre class="drawio-xml">{xml}</pre>'
                for i, xml in enumerate(diagram_xmls)
            )
            body_html = (
                f"<h1>Architecture Options: {issue_key}</h1>"
                f"<pre>{architecture_text}</pre>"
                f"{diagrams_html}"
            )

            title = f"Architecture Options: {issue_key}"
            space_key = project.project_key

            result = await client.create_page(space_key, title, body_html)
            page_id = result.get("id", "")
            if not page_id:
                logger.warning(
                    "Confluence page created but no id returned for ticket %s", issue_key
                )
                return ""

            page_url = client.get_page_url(space_key, page_id)
            logger.info(
                "Architecture published to Confluence for ticket %s: %s",
                issue_key,
                page_url,
            )
            return page_url

        except Exception as exc:
            # T-04-03: all exceptions caught; graceful degradation — never expose token
            logger.warning(
                "publish_architecture failed for ticket %s: %s — returning empty URL",
                issue_key,
                exc,
            )
            return ""


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


async def publish_architecture(
    project: Project,
    issue_key: str,
    architecture_text: str,
    diagram_xmls: list[str],
) -> str:
    """Module-level convenience wrapper for ConfluenceClient.publish_architecture.

    Constructs a ConfluenceClient from project credentials and delegates to
    the instance method. Used by architecture_pipeline for direct import.

    Args:
        project: Project ORM with confluence_url, confluence_token, project_key.
        issue_key: Jira issue key.
        architecture_text: Full options text.
        diagram_xmls: List of mxGraph XML strings.

    Returns:
        Page URL string on success; "" on any failure.
    """
    try:
        conf_token = decrypt_credential(project.confluence_token)
        client = ConfluenceClient(project.confluence_url, conf_token)
        return await client.publish_architecture(project, issue_key, architecture_text, diagram_xmls)
    except Exception as exc:
        logger.warning(
            "publish_architecture (module fn) failed for ticket %s: %s — returning empty URL",
            issue_key,
            exc,
        )
        return ""
