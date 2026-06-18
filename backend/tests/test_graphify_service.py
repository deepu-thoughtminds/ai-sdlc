"""TDD tests for graphify_service.

Tests (3 total):
1. test_get_codebase_summary_returns_struct - mocked GitHub API returns formatted StructuredCodebaseSummary
2. test_get_codebase_summary_on_github_error - 403 response returns empty StructuredCodebaseSummary, no exception
3. test_get_codebase_summary_filters_to_python - tree with mixed file types; key_files only includes .py paths

Uses respx for httpx mocking.
"""

import base64
import os

import httpx
import pytest
import respx

from services.graphify_service import StructuredCodebaseSummary, get_codebase_summary

GITHUB_URL = "https://github.com/org/myrepo"
GITHUB_TOKEN = "ghp_test_token"

# Override GitHub API base for tests
os.environ.setdefault("GITHUB_API_BASE", "https://api.github.com")


def _make_tree_response(paths: list[str]) -> dict:
    """Build a GitHub tree API response from a list of file paths."""
    return {
        "tree": [{"path": p, "type": "blob"} for p in paths],
        "truncated": False,
    }


def _encode_content(text: str) -> str:
    """Base64-encode file content as GitHub API returns it."""
    return base64.b64encode(text.encode()).decode()


@respx.mock
def test_get_codebase_summary_returns_struct():
    """Mock GitHub API with 5 tree paths + 2 Python files; assert StructuredCodebaseSummary fields."""
    paths = [
        "backend/main.py",
        "backend/database.py",
        "frontend/src/app/page.tsx",
        "README.md",
        "docker-compose.yml",
    ]

    # Mock tree endpoint
    respx.get("https://api.github.com/repos/org/myrepo/git/trees/HEAD").mock(
        return_value=httpx.Response(200, json=_make_tree_response(paths))
    )

    # Mock content for .py files
    main_content = '"""Main application module."""\n\nfrom fastapi import FastAPI\n\napp = FastAPI()'
    db_content = '"""Database module.\n\nHandles SQLAlchemy setup.\n"""\n\nimport os'

    respx.get("https://api.github.com/repos/org/myrepo/contents/backend/main.py").mock(
        return_value=httpx.Response(
            200,
            json={"content": _encode_content(main_content), "encoding": "base64"},
        )
    )
    respx.get("https://api.github.com/repos/org/myrepo/contents/backend/database.py").mock(
        return_value=httpx.Response(
            200,
            json={"content": _encode_content(db_content), "encoding": "base64"},
        )
    )

    result = get_codebase_summary(GITHUB_URL, GITHUB_TOKEN)

    assert isinstance(result, StructuredCodebaseSummary)
    # directory_tree should include all file paths
    assert "backend/main.py" in result.directory_tree
    assert "README.md" in result.directory_tree
    # key_files should include only .py files
    assert "backend/main.py" in result.key_files
    assert "backend/database.py" in result.key_files
    # no .ts or .md files in key_files
    for f in result.key_files:
        assert f.endswith(".py"), f"Non-Python file in key_files: {f}"
    # module_docs should have entries for the .py files
    assert "backend/main.py" in result.module_docs
    assert "backend/database.py" in result.module_docs


@respx.mock
def test_get_codebase_summary_on_github_error():
    """403 response from GitHub → returns empty StructuredCodebaseSummary, no exception raised."""
    respx.get("https://api.github.com/repos/org/myrepo/git/trees/HEAD").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )

    result = get_codebase_summary(GITHUB_URL, GITHUB_TOKEN)

    assert isinstance(result, StructuredCodebaseSummary)
    assert result.directory_tree == ""
    assert result.key_files == []
    assert result.module_docs == {}


@respx.mock
def test_get_codebase_summary_filters_to_python():
    """10 tree paths with mixed file types; key_files must only include .py paths."""
    mixed_paths = [
        "backend/main.py",
        "backend/database.py",
        "backend/services/llm_router.py",
        "frontend/src/app/page.tsx",
        "frontend/src/lib/api.ts",
        "docker-compose.yml",
        "README.md",
        ".env.example",
        "backend/tests/test_projects.py",
        "Makefile",
    ]

    respx.get("https://api.github.com/repos/org/myrepo/git/trees/HEAD").mock(
        return_value=httpx.Response(200, json=_make_tree_response(mixed_paths))
    )

    # Mock content fetches for .py files (return minimal content)
    py_files = [p for p in mixed_paths if p.endswith(".py")]
    for path in py_files:
        respx.get(f"https://api.github.com/repos/org/myrepo/contents/{path}").mock(
            return_value=httpx.Response(
                200,
                json={"content": _encode_content("# module\n"), "encoding": "base64"},
            )
        )

    result = get_codebase_summary(GITHUB_URL, GITHUB_TOKEN)

    assert isinstance(result, StructuredCodebaseSummary)
    for f in result.key_files:
        assert f.endswith(".py"), f"Non-Python file in key_files: {f}"
    # All 4 .py files should appear
    expected_py = [p for p in mixed_paths if p.endswith(".py")]
    for p in expected_py:
        assert p in result.key_files, f"Expected .py file missing from key_files: {p}"
