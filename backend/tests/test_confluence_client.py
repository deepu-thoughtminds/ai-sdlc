"""Tests for confluence_client.ConfluenceClient.

Covers:
1. create_page delegates to services.hermes_client.create_confluence_page
2. get_page_url construction (pure, no network call)
3. find_page — delegates to hermes_client, returns None when not found
4. publish_architecture diagram template (is_complex=True) — six sections +
   drawio-xml block + viewer link
5. publish_architecture text-only template (is_complex=False) — four sections,
   no drawio-xml block
6. HTML-escaping of special characters in architecture text
7. find-or-update idempotency — second publish_architecture call for the same
   issue_key updates (PUT) instead of creating (POST)
8. update_page sends incremented version number
9. graceful degradation — any exception returns ""

Uses unittest.mock.AsyncMock to patch services.hermes_client functions
(patched at services.confluence_client.*  — patch where imported, not where defined).
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# Set env vars before any app imports.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)

from services.confluence_client import ConfluenceClient  # noqa: E402


CONFLUENCE_BASE = "https://confluence.example.com"
CONF_TOKEN = "confluence-token-plain"
CONF_EMAIL = "confluence@example.com"


def _make_client() -> ConfluenceClient:
    return ConfluenceClient(base_url=CONFLUENCE_BASE, token=CONF_TOKEN, email=CONF_EMAIL)


def _make_mock_project():
    """Return a mock Project with confluence credentials."""
    from cryptography.fernet import Fernet as _Fernet
    key = os.environ["ENCRYPTION_KEY"].encode()
    encrypted_token = _Fernet(key).encrypt(CONF_TOKEN.encode()).decode()

    p = MagicMock()
    p.id = 1
    p.project_key = "PROJ"
    p.jira_url = "https://jira.example.com"
    p.jira_email = CONF_EMAIL
    p.confluence_url = CONFLUENCE_BASE
    p.confluence_token = encrypted_token
    return p


def _created_page_dict(page_id: str = "12345") -> dict:
    return {
        "id": page_id,
        "space": {"key": "PROJ"},
        "_links": {"webui": f"/spaces/PROJ/pages/{page_id}"},
    }


def _found_page_dict(page_id: str = "555", version: int = 3) -> dict:
    return {"id": page_id, "version": {"number": version}}


def _updated_page_dict(page_id: str = "555") -> dict:
    return {
        "id": page_id,
        "space": {"key": "PROJ"},
        "_links": {"webui": f"/spaces/PROJ/pages/{page_id}"},
    }


# ---------------------------------------------------------------------------
# create_page delegate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_page_delegates_to_hermes_client():
    """create_page calls create_confluence_page with correct args and returns the result."""
    mock_create = AsyncMock(return_value=_created_page_dict("12345"))
    with patch("services.confluence_client.create_confluence_page", mock_create):
        client = _make_client()
        result = await client.create_page("PROJ", "Arch Options TICKET-1", "<h1>Options</h1>")

    mock_create.assert_called_once_with(
        CONFLUENCE_BASE, CONF_EMAIL, CONF_TOKEN, "PROJ", "Arch Options TICKET-1", "<h1>Options</h1>"
    )
    assert result["id"] == "12345"


@pytest.mark.asyncio
async def test_create_page_parent_id_ignored():
    """create_page accepts parent_id parameter but does not pass it to hermes_client (MCP tool limitation)."""
    mock_create = AsyncMock(return_value=_created_page_dict("99"))
    with patch("services.confluence_client.create_confluence_page", mock_create):
        client = _make_client()
        result = await client.create_page("PROJ", "Title", "<p>body</p>", parent_id="parent-42")

    # parent_id should NOT appear in the hermes_client call
    mock_create.assert_called_once_with(
        CONFLUENCE_BASE, CONF_EMAIL, CONF_TOKEN, "PROJ", "Title", "<p>body</p>"
    )
    assert result["id"] == "99"


# ---------------------------------------------------------------------------
# get_page_url pure construction test
# ---------------------------------------------------------------------------


def test_get_page_url_constructs_correctly():
    """get_page_url returns the correct URL without making any network call."""
    client = _make_client()
    url = client.get_page_url("PROJ", "12345")
    assert url == f"{CONFLUENCE_BASE}/wiki/spaces/PROJ/pages/12345"


def test_get_page_url_does_not_double_wiki_for_cloud_base():
    """A base_url already ending in /wiki (Atlassian Cloud) must not yield /wiki/wiki."""
    client = ConfluenceClient(
        base_url=f"{CONFLUENCE_BASE}/wiki", token=CONF_TOKEN, email=CONF_EMAIL
    )
    url = client.get_page_url("SCRUM", "7667750")
    assert url == f"{CONFLUENCE_BASE}/wiki/spaces/SCRUM/pages/7667750"
    assert "/wiki/wiki/" not in url


# ---------------------------------------------------------------------------
# find_page tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_page_returns_none_when_not_found():
    """find_page returns None when hermes_client returns None."""
    mock_find = AsyncMock(return_value=None)
    with patch("services.confluence_client.find_confluence_page", mock_find):
        client = _make_client()
        result = await client.find_page("PROJ", "Architecture: TICKET-1")

    mock_find.assert_called_once_with(
        CONFLUENCE_BASE, CONF_EMAIL, CONF_TOKEN, "PROJ", "Architecture: TICKET-1"
    )
    assert result is None


@pytest.mark.asyncio
async def test_find_page_returns_result_when_found():
    """find_page returns the page dict when hermes_client finds a match."""
    page = _found_page_dict(page_id="555", version=3)
    mock_find = AsyncMock(return_value=page)
    with patch("services.confluence_client.find_confluence_page", mock_find):
        client = _make_client()
        result = await client.find_page("PROJ", "Architecture: TICKET-1")

    assert result is not None
    assert result["id"] == "555"
    assert result["version"]["number"] == 3


# ---------------------------------------------------------------------------
# publish_architecture template tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_architecture_diagram_template_contains_drawio_block():
    """is_complex=True produces all six headings + drawio-xml block + viewer link."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("12345"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Summary text",
            approach="Approach text",
            key_decisions="Decisions text",
            risks="Risks text",
            is_complex=True,
            component_breakdown="Component breakdown text",
            integration_points="Integration points text",
            diagram_xml="<mxGraphModel/>",
            viewer_url="https://app.diagrams.net/?xml=abc",
        )

    assert isinstance(result, str)
    assert len(result) > 0

    # Inspect the body_html passed to create_confluence_page
    _, _, _, _, _, body_html = mock_create.call_args[0]

    for heading in (
        "Summary",
        "Approach",
        "Component Breakdown",
        "Integration Points",
        "Key Decisions",
        "Risks",
    ):
        assert f">{heading}<" in body_html

    assert '<pre class="drawio-xml">' in body_html
    # The drawio XML is HTML-escaped inside the <pre> block.
    assert "&lt;mxGraphModel/&gt;" in body_html
    assert "https://app.diagrams.net/?xml=abc" in body_html


@pytest.mark.asyncio
async def test_publish_qa_report_creates_page_with_title_and_body():
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("777"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_qa_report(
            mock_project, "TICKET-1", "QA results for TICKET-1:\n\n- npm test: PASSED"
        )

    assert result == client.get_page_url("PROJ", "777")
    _, _, _, space_key, title, body_html = mock_create.call_args[0]
    assert title == "QA Report: TICKET-1"
    assert "npm test: PASSED" in body_html


@pytest.mark.asyncio
async def test_publish_qa_report_updates_existing_page():
    page = _found_page_dict(page_id="555", version=3)
    mock_find = AsyncMock(return_value=page)
    mock_update = AsyncMock(return_value=_updated_page_dict())
    mock_create = AsyncMock(return_value=_created_page_dict("12345"))

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        result = await client.publish_qa_report(_make_mock_project(), "TICKET-1", "report")

    mock_create.assert_not_called()
    mock_update.assert_called_once()
    assert mock_update.call_args[0][3] == "555"  # page_id arg to update_confluence_page
    assert mock_update.call_args[0][-1] == 4  # version = current (3) + 1
    assert result == client.get_page_url("PROJ", "555")


@pytest.mark.asyncio
async def test_publish_qa_report_returns_empty_string_on_exception():
    mock_find = AsyncMock(side_effect=RuntimeError("network down"))

    with patch("services.confluence_client.find_confluence_page", mock_find):
        client = _make_client()
        result = await client.publish_qa_report(_make_mock_project(), "TICKET-1", "report")

    assert result == ""


@pytest.mark.asyncio
async def test_publish_architecture_text_only_template_excludes_diagram_block():
    """is_complex=False produces exactly four text-only headings, no drawio-xml block."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("12345"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Summary text",
            approach="Approach text",
            key_decisions="Decisions text",
            risks="Risks text",
            is_complex=False,
        )

    assert isinstance(result, str)
    assert len(result) > 0

    _, _, _, _, _, body_html = mock_create.call_args[0]

    for heading in ("Summary", "Approach", "Key Decisions", "Risks"):
        assert f">{heading}<" in body_html

    for heading in ("Component Breakdown", "Integration Points"):
        assert f">{heading}<" not in body_html

    assert "drawio-xml" not in body_html


@pytest.mark.asyncio
async def test_publish_architecture_escapes_html_special_chars():
    """Architecture text containing HTML special chars is escaped, never raw in body_html."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("12345"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    dangerous = '<script>alert("xss")</script> & more <b>bold</b>'

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary=dangerous,
            approach="Approach text",
            key_decisions="Decisions text",
            risks="Risks text",
            is_complex=False,
        )

    _, _, _, _, _, body_html = mock_create.call_args[0]

    assert "<script>" not in body_html
    assert "&lt;script&gt;" in body_html
    assert "&amp;" in body_html
    assert "&quot;" in body_html


# ---------------------------------------------------------------------------
# find-or-update idempotency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_architecture_creates_when_no_existing_page():
    """publish_architecture calls create_page when find_page returns None."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("12345"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Summary",
            approach="Approach",
            key_decisions="Decisions",
            risks="Risks",
        )

    assert "12345" in result
    mock_create.assert_called_once()
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_publish_architecture_updates_existing_page_instead_of_creating():
    """Second publish_architecture for same issue_key updates (PUT), not creates (POST)."""
    existing = _found_page_dict(page_id="555", version=3)
    mock_find = AsyncMock(return_value=existing)
    mock_create = AsyncMock(return_value=_created_page_dict())
    mock_update = AsyncMock(return_value=_updated_page_dict("555"))

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Updated summary",
            approach="Updated approach",
            key_decisions="Updated decisions",
            risks="Updated risks",
        )

    assert "555" in result
    mock_create.assert_not_called()
    mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_update_page_sends_incremented_version():
    """update_page is called with version = current_version + 1."""
    existing = _found_page_dict(page_id="555", version=3)
    mock_find = AsyncMock(return_value=existing)
    mock_create = AsyncMock(return_value=_created_page_dict())
    mock_update = AsyncMock(return_value=_updated_page_dict("555"))

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Summary",
            approach="Approach",
            key_decisions="Decisions",
            risks="Risks",
        )

    # update_confluence_page(base_url, email, token, page_id, title, body_html, version)
    call_args = mock_update.call_args[0]
    version_arg = call_args[6]  # 7th positional arg
    assert version_arg == 4  # 3 + 1


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_architecture_graceful_on_create_failure():
    """If create_confluence_page raises, publish_architecture returns '' (no exception)."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(side_effect=RuntimeError("hermes 500"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Summary",
            approach="Approach",
            key_decisions="Decisions",
            risks="Risks",
        )

    assert result == ""


@pytest.mark.asyncio
async def test_publish_architecture_graceful_on_find_failure():
    """If find_confluence_page raises, publish_architecture returns '' (no exception)."""
    mock_find = AsyncMock(side_effect=RuntimeError("hermes search error"))
    mock_create = AsyncMock(return_value=_created_page_dict())
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_architecture(
            mock_project,
            "TICKET-1",
            summary="Summary",
            approach="Approach",
            key_decisions="Decisions",
            risks="Risks",
        )

    assert result == ""


# ---------------------------------------------------------------------------
# _render_sonar_section and publish_qa_report sonar integration — REPORT-01..03
# ---------------------------------------------------------------------------

from services.confluence_client import _render_sonar_section  # noqa: E402
from services.sonar_scanner import SonarMetrics  # noqa: E402


def _make_sonar_metrics(gate="PASSED", coverage=82.5) -> SonarMetrics:
    return SonarMetrics(
        gate_status=gate,
        bugs=3,
        vulnerabilities=1,
        code_smells=10,
        coverage=coverage,
        duplications=4.2,
        dashboard_url="http://sonar:9000/dashboard?id=org__repo",
    )


class TestRenderSonarSection:
    def test_none_returns_unavailable_note(self):
        """_render_sonar_section(None) contains h2 header and unavailable note (REPORT-03)."""
        result = _render_sonar_section(None)
        assert "<h2>" in result
        assert "SonarQube" in result
        assert "unavailable" in result.lower()

    def test_passed_gate_status_present(self):
        """_render_sonar_section with PASSED metrics → contains 'PASSED'."""
        result = _render_sonar_section(_make_sonar_metrics(gate="PASSED"))
        assert "PASSED" in result

    def test_failed_gate_status_present(self):
        """gate_status FAILED → contains 'FAILED'."""
        result = _render_sonar_section(_make_sonar_metrics(gate="FAILED"))
        assert "FAILED" in result

    def test_metric_counts_present(self):
        """Rendered section contains bug/vuln/code-smell/duplication values."""
        result = _render_sonar_section(_make_sonar_metrics())
        assert "3" in result   # bugs
        assert "1" in result   # vulnerabilities
        assert "10" in result  # code smells
        assert "4.2" in result or "4.2%" in result  # duplications

    def test_dashboard_link_present(self):
        """Dashboard URL appears in an anchor tag (REPORT-02)."""
        result = _render_sonar_section(_make_sonar_metrics())
        assert "http://sonar:9000/dashboard?id=org__repo" in result
        assert "<a " in result

    def test_coverage_value_present_when_set(self):
        """coverage=82.5 → '82.5' appears in rendered HTML (REPORT-02)."""
        result = _render_sonar_section(_make_sonar_metrics(coverage=82.5))
        assert "82.5" in result

    def test_coverage_none_renders_na(self):
        """coverage=None → 'N/A' appears in rendered HTML (REPORT-02)."""
        metrics = SonarMetrics(
            gate_status="PASSED", bugs=0, vulnerabilities=0, code_smells=0,
            coverage=None, duplications=0.0,
            dashboard_url="http://sonar:9000/dashboard?id=org__repo",
        )
        result = _render_sonar_section(metrics)
        assert "N/A" in result


@pytest.mark.asyncio
async def test_publish_qa_report_no_sonar_metrics_arg():
    """publish_qa_report() called without sonar_metrics → succeeds (backward compat, REPORT-01)."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("888"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        # Call without sonar_metrics kwarg — should not error
        result = await client.publish_qa_report(
            mock_project, "TICKET-1", "QA passed.", ""
        )

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_publish_qa_report_sonar_metrics_none_includes_sonar_section():
    """publish_qa_report(sonar_metrics=None) → body has SonarQube h2 section (REPORT-01+03)."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("889"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_qa_report(
            mock_project, "TICKET-1", "QA passed.", "", sonar_metrics=None
        )

    assert isinstance(result, str)
    assert len(result) > 0
    # The body passed to create_page must contain a SonarQube section
    _, _, _, _, _, body_html = mock_create.call_args[0]
    assert "SonarQube" in body_html


@pytest.mark.asyncio
async def test_publish_qa_report_with_sonar_metrics_includes_dashboard_link():
    """publish_qa_report(sonar_metrics=SonarMetrics) → body has dashboard link (REPORT-01+02)."""
    mock_find = AsyncMock(return_value=None)
    mock_create = AsyncMock(return_value=_created_page_dict("890"))
    mock_update = AsyncMock(return_value=_updated_page_dict())

    with patch("services.confluence_client.find_confluence_page", mock_find), \
         patch("services.confluence_client.create_confluence_page", mock_create), \
         patch("services.confluence_client.update_confluence_page", mock_update):

        client = _make_client()
        mock_project = _make_mock_project()

        result = await client.publish_qa_report(
            mock_project, "TICKET-1", "QA done.", "",
            sonar_metrics=_make_sonar_metrics(),
        )

    assert isinstance(result, str)
    assert len(result) > 0
    _, _, _, _, _, body_html = mock_create.call_args[0]
    assert "http://sonar:9000/dashboard?id=org__repo" in body_html
