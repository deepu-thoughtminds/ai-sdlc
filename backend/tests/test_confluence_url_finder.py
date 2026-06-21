"""Unit tests for backend/services/confluence_url_finder.py — pure function, no I/O."""
import pytest

from services.confluence_url_finder import find_latest_architecture_url


# ---------------------------------------------------------------------------
# Helper: build a minimal Jira comment dict
# ---------------------------------------------------------------------------

def _comment(body: str, id_: str = "c1") -> dict:
    return {"id": id_, "body": body, "author": {"displayName": "Alice"}}


# ---------------------------------------------------------------------------
# 1. Returns None when comments list is empty
# ---------------------------------------------------------------------------

def test_returns_none_when_no_comments():
    """find_latest_architecture_url returns None for an empty comment list."""
    assert find_latest_architecture_url([]) is None


# ---------------------------------------------------------------------------
# 2. Returns None when no Confluence URL is present in any comment
# ---------------------------------------------------------------------------

def test_returns_none_when_no_confluence_url():
    """find_latest_architecture_url returns None when no Confluence URL found."""
    comments = [
        _comment("Here is some text without any URL", "c1"),
        _comment("Another comment with https://github.com/org/repo not a Confluence URL", "c2"),
    ]
    assert find_latest_architecture_url(comments) is None


# ---------------------------------------------------------------------------
# 3. Returns Confluence URL when found in a comment
# ---------------------------------------------------------------------------

def test_returns_confluence_url_when_found():
    """find_latest_architecture_url returns the URL when a Confluence page URL is present."""
    url = "https://myteam.atlassian.net/wiki/spaces/PROJ/pages/123456789"
    comments = [_comment(f"Architecture page: {url}", "c1")]
    result = find_latest_architecture_url(comments)
    assert result == url


# ---------------------------------------------------------------------------
# 4. Returns most recent (last) Confluence URL when multiple comments contain URLs
# ---------------------------------------------------------------------------

def test_returns_most_recent_url():
    """find_latest_architecture_url returns URL from the newest comment (iterates newest-first)."""
    old_url = "https://myteam.atlassian.net/wiki/spaces/PROJ/pages/111111111"
    new_url = "https://myteam.atlassian.net/wiki/spaces/PROJ/pages/999999999"
    # Jira returns oldest-first; newest comment is last in list
    comments = [
        _comment(f"Old architecture: {old_url}", "c1"),
        _comment("Just a discussion comment with no URL", "c2"),
        _comment(f"Updated architecture: {new_url}", "c3"),
    ]
    result = find_latest_architecture_url(comments)
    assert result == new_url


# ---------------------------------------------------------------------------
# 5. Returns URL from comment body even when body is nested in author/other fields
# ---------------------------------------------------------------------------

def test_searches_body_field_not_author():
    """find_latest_architecture_url searches the body field, not other comment fields."""
    url = "https://myteam.atlassian.net/wiki/spaces/ARCH/pages/42"
    comments = [
        {
            "id": "c1",
            "body": f"See architecture at {url}",
            "author": {"displayName": "Bot", "emailAddress": "bot@example.com"},
        }
    ]
    result = find_latest_architecture_url(comments)
    assert result == url


# ---------------------------------------------------------------------------
# 6. Handles comments without a body field gracefully
# ---------------------------------------------------------------------------

def test_handles_missing_body_field():
    """find_latest_architecture_url skips comments without a body field."""
    url = "https://myteam.atlassian.net/wiki/spaces/PROJ/pages/555"
    comments = [
        {"id": "c1", "author": {"displayName": "Alice"}},  # no body key
        _comment(f"Architecture: {url}", "c2"),
    ]
    result = find_latest_architecture_url(comments)
    assert result == url


# ---------------------------------------------------------------------------
# 7. Returns None when body is not a string (defensive)
# ---------------------------------------------------------------------------

def test_handles_non_string_body():
    """find_latest_architecture_url handles non-string body values without crashing."""
    comments = [
        {"id": "c1", "body": {"content": "structured content not string"}},
    ]
    result = find_latest_architecture_url(comments)
    assert result is None


# ---------------------------------------------------------------------------
# 8. Matches various valid Confluence URL patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://company.atlassian.net/wiki/spaces/ENG/pages/1234567890",
    "https://myorg.atlassian.net/wiki/spaces/PROJ/pages/987654321",
    "http://confluence.internal/wiki/spaces/TEAM/pages/42",
])
def test_matches_various_confluence_url_patterns(url):
    """find_latest_architecture_url recognises multiple valid Confluence URL shapes."""
    comments = [_comment(f"Architecture doc: {url}")]
    result = find_latest_architecture_url(comments)
    assert result == url


# ---------------------------------------------------------------------------
# 9. Does not match non-Confluence URLs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    "See https://github.com/org/repo for the code",
    "Check https://docs.example.com/wiki for docs",
    "Visit https://notion.so/page-id for notes",
])
def test_does_not_match_non_confluence_urls(body):
    """find_latest_architecture_url does not return non-Confluence URLs."""
    comments = [_comment(body)]
    assert find_latest_architecture_url(comments) is None
