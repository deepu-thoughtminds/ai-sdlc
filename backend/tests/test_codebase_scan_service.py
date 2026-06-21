"""TDD tests for codebase_scan_service — SCAN-02, SCAN-03 (Phase 18).

Tests cover:
1. _parse_owner_repo — valid slug, .git suffix, invalid slug
2. _select_key_files — SKIP_DIRS, SKIP_EXTENSIONS, MAX_FILES=25 cap
3. _build_ascii_tree — tree notation, depth cap, directory-before-file ordering
4. _detect_tech_stack — Python, FastAPI, Docker detection
5. _build_markdown — all four required section headers present
6. run() — invalid repo returns immediately, Trees truncated continues,
   Contents 404 skips file, PUT 403 logs and raises

Uses unittest.mock.patch + pytest.mark.asyncio; respx for httpx mocking.
github_token is NEVER asserted in log output (T-18-01).
"""

import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ=")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GITHUB_API_BASE"] = "https://api.github.com"

# ---------------------------------------------------------------------------
# Import helpers — must come after env setup
# ---------------------------------------------------------------------------

from services.codebase_scan_service import (  # noqa: E402
    _build_ascii_tree,
    _build_markdown,
    _detect_tech_stack,
    _parse_owner_repo,
    _select_key_files,
    run,
)

# ---------------------------------------------------------------------------
# _parse_owner_repo
# ---------------------------------------------------------------------------


def test_parse_owner_repo_valid_slug():
    """'org/repo' parses to ('org', 'repo')."""
    result = _parse_owner_repo("org/repo")
    assert result == ("org", "repo"), f"Expected ('org', 'repo'), got {result}"


def test_parse_owner_repo_invalid_returns_none():
    """'not-a-slug' (no slash) returns None."""
    result = _parse_owner_repo("not-a-slug")
    assert result is None, f"Expected None, got {result}"


def test_parse_owner_repo_empty_returns_none():
    """Empty string returns None."""
    result = _parse_owner_repo("")
    assert result is None


def test_parse_owner_repo_extra_slash_returns_none():
    """'org/repo/extra' (two slashes) returns None — not a valid owner/repo slug."""
    result = _parse_owner_repo("org/repo/extra")
    assert result is None


# ---------------------------------------------------------------------------
# _select_key_files
# ---------------------------------------------------------------------------


def test_select_key_files_skips_node_modules():
    """node_modules/* paths are excluded."""
    paths = ["node_modules/x.js", "README.md", "backend/main.py", "dist/out.js"]
    selected = _select_key_files(paths)
    assert "node_modules/x.js" not in selected
    assert "dist/out.js" not in selected
    assert "README.md" in selected or "backend/main.py" in selected


def test_select_key_files_respects_max_files():
    """Returns at most 25 paths."""
    paths = [f"src/file_{i}.py" for i in range(100)]
    selected = _select_key_files(paths)
    assert len(selected) <= 25


def test_select_key_files_skips_png_extension():
    """.png files are excluded."""
    paths = ["assets/logo.png", "backend/main.py"]
    selected = _select_key_files(paths)
    assert "assets/logo.png" not in selected


def test_select_key_files_prioritises_readme():
    """README.md comes before arbitrary source files in the selected list."""
    paths = ["src/a.py", "src/b.py", "README.md"]
    selected = _select_key_files(paths)
    assert "README.md" in selected
    # README should be first
    assert selected[0] == "README.md"


# ---------------------------------------------------------------------------
# _build_ascii_tree
# ---------------------------------------------------------------------------


def test_build_ascii_tree_returns_string():
    """Returns a non-empty string for a list of paths."""
    paths = ["backend/main.py", "README.md"]
    tree = _build_ascii_tree(paths)
    assert isinstance(tree, str)
    assert len(tree) > 0


def test_build_ascii_tree_contains_tree_notation():
    """Result contains ├── or └── tree notation characters."""
    paths = ["backend/main.py", "README.md", "backend/database.py"]
    tree = _build_ascii_tree(paths)
    assert "├──" in tree or "└──" in tree


def test_build_ascii_tree_depth_cap():
    """Paths deeper than max_depth=3 are collapsed with '...'."""
    deep_paths = ["a/b/c/d/e/deep_file.py"]
    tree = _build_ascii_tree(deep_paths, max_depth=3)
    assert "..." in tree


def test_build_ascii_tree_skips_skip_dirs():
    """node_modules paths are excluded from the tree."""
    paths = ["backend/main.py", "node_modules/express/index.js"]
    tree = _build_ascii_tree(paths)
    assert "node_modules" not in tree


# ---------------------------------------------------------------------------
# _detect_tech_stack
# ---------------------------------------------------------------------------


def test_detect_tech_stack_python_from_pyproject():
    """Detects Python when 'pyproject.toml' is in all_paths."""
    paths = ["pyproject.toml", "backend/main.py"]
    stack = _detect_tech_stack(paths, {})
    names = " ".join(stack).lower()
    assert "python" in names


def test_detect_tech_stack_fastapi_from_manifest():
    """Detects FastAPI when 'fastapi' appears in pyproject.toml content."""
    paths = ["pyproject.toml"]
    manifest_contents = {"pyproject.toml": "[tool.poetry.dependencies]\nfastapi = '*'"}
    stack = _detect_tech_stack(paths, manifest_contents)
    names = " ".join(stack).lower()
    assert "fastapi" in names


def test_detect_tech_stack_docker_from_dockerfile():
    """Detects Docker when 'Dockerfile' is in all_paths."""
    paths = ["Dockerfile", "docker-compose.yml"]
    stack = _detect_tech_stack(paths, {})
    names = " ".join(stack).lower()
    assert "docker" in names


def test_detect_tech_stack_no_manifest_empty():
    """Returns empty list when no recognisable manifest files present."""
    stack = _detect_tech_stack(["src/random.txt"], {})
    assert isinstance(stack, list)
    # No manifest → nothing detected
    assert len(stack) == 0


# ---------------------------------------------------------------------------
# _build_markdown
# ---------------------------------------------------------------------------


def test_build_markdown_contains_required_sections():
    """Returned markdown contains all four required section headers."""
    md = _build_markdown(
        owner="org",
        repo="myrepo",
        stack=["Python (pyproject.toml)"],
        tree="repo-root/\n└── README.md",
        key_file_contents={"README.md": "# My Repo"},
        module_summary=[("README.md", "Documentation")],
        files_read=1,
    )
    assert "## Tech Stack" in md
    assert "## Directory Structure" in md
    assert "## Key Files" in md
    assert "## Module Summary" in md


def test_build_markdown_title_contains_owner_repo():
    """Title line contains 'org/myrepo'."""
    md = _build_markdown(
        owner="org",
        repo="myrepo",
        stack=[],
        tree="",
        key_file_contents={},
        module_summary=[],
        files_read=0,
    )
    assert "org/myrepo" in md


def test_build_markdown_no_manifest_placeholder():
    """Empty stack produces 'No manifest files detected.' placeholder."""
    md = _build_markdown(
        owner="a",
        repo="b",
        stack=[],
        tree="",
        key_file_contents={},
        module_summary=[],
        files_read=0,
    )
    assert "No manifest files detected." in md


# ---------------------------------------------------------------------------
# run() — async coroutine behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_invalid_repo_returns_early():
    """run() with invalid github_repo returns immediately without calling GitHub API."""
    db = MagicMock()
    # No httpx mock — any actual HTTP call would fail (and should not happen)
    # We patch httpx.AsyncClient to assert it was never entered
    with patch("services.codebase_scan_service.httpx.AsyncClient") as mock_client_cls:
        await run("not-a-valid/repo/extra/parts", "ghp_token", 1, db)
        mock_client_cls.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_run_trees_truncated_continues():
    """Trees API truncated=true → logs warning but continues to process blobs."""
    respx.get("https://api.github.com/repos/org/repo").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=httpx.Response(
            200,
            json={
                "tree": [{"path": "README.md", "type": "blob"}],
                "truncated": True,
            },
        )
    )
    # Contents fetch for README.md
    readme_b64 = base64.b64encode(b"# Hello").decode()
    respx.get("https://api.github.com/repos/org/repo/contents/README.md").mock(
        return_value=httpx.Response(200, json={"content": readme_b64, "sha": None})
    )
    # Idempotency GET for .hermes/codebase.md → 404
    respx.get("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    # PUT to commit
    respx.put("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(201, json={"content": {"sha": "newsha"}})
    )

    db = MagicMock()
    # Should complete without raising
    await run("org/repo", "ghp_token", 1, db)


@pytest.mark.asyncio
@respx.mock
async def test_run_contents_404_skips_file():
    """Contents API 404 for a single file → skips that file, continues scan."""
    respx.get("https://api.github.com/repos/org/repo").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=httpx.Response(
            200,
            json={
                "tree": [
                    {"path": "README.md", "type": "blob"},
                    {"path": "missing.py", "type": "blob"},
                ],
                "truncated": False,
            },
        )
    )
    readme_b64 = base64.b64encode(b"# Hello").decode()
    respx.get("https://api.github.com/repos/org/repo/contents/README.md").mock(
        return_value=httpx.Response(200, json={"content": readme_b64, "sha": None})
    )
    # 404 for missing.py
    respx.get("https://api.github.com/repos/org/repo/contents/missing.py").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    respx.get("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    respx.put("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(201, json={"content": {"sha": "newsha"}})
    )

    db = MagicMock()
    await run("org/repo", "ghp_token", 1, db)  # must not raise


@pytest.mark.asyncio
@respx.mock
async def test_run_put_403_raises():
    """PUT .hermes/codebase.md returning 403 → run() raises an exception."""
    respx.get("https://api.github.com/repos/org/repo").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=httpx.Response(
            200,
            json={
                "tree": [{"path": "README.md", "type": "blob"}],
                "truncated": False,
            },
        )
    )
    readme_b64 = base64.b64encode(b"# Hello").decode()
    respx.get("https://api.github.com/repos/org/repo/contents/README.md").mock(
        return_value=httpx.Response(200, json={"content": readme_b64, "sha": None})
    )
    respx.get("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    respx.put("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )

    db = MagicMock()
    with pytest.raises(Exception):
        await run("org/repo", "ghp_token", 1, db)


# ---------------------------------------------------------------------------
# Additional coverage — 18-02: max-files budget, sha idempotency, Next.js
# ---------------------------------------------------------------------------


def test_select_key_files_max_budget():
    """30 eligible paths produces exactly MAX_FILES (25) entries."""
    paths = [f"src/file_{i}.py" for i in range(30)]
    selected = _select_key_files(paths)
    assert len(selected) == 25


def test_detect_tech_stack_nextjs():
    """Detects Next.js when 'next' appears in package.json content."""
    paths = ["package.json"]
    manifest_contents = {"package.json": '{"dependencies": {"next": "13.0"}}'}
    stack = _detect_tech_stack(paths, manifest_contents)
    names = " ".join(stack).lower()
    assert "next.js" in names


@pytest.mark.asyncio
@respx.mock
async def test_run_idempotent_put_includes_sha():
    """When .hermes/codebase.md already exists (200 + sha), PUT body includes that sha."""
    respx.get("https://api.github.com/repos/org/repo").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=httpx.Response(
            200,
            json={"tree": [{"path": "README.md", "type": "blob"}], "truncated": False},
        )
    )
    readme_b64 = base64.b64encode(b"# Hello").decode()
    respx.get("https://api.github.com/repos/org/repo/contents/README.md").mock(
        return_value=httpx.Response(200, json={"content": readme_b64, "sha": None})
    )
    old_b64 = base64.b64encode(b"old content").decode()
    respx.get("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(200, json={"sha": "abc123", "content": old_b64})
    )
    put_route = respx.put("https://api.github.com/repos/org/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(200, json={"content": {"sha": "newsha"}})
    )

    db = MagicMock()
    await run("org/repo", "ghp_token", 1, db)

    assert put_route.called
    put_request = put_route.calls.last.request
    import json as _json

    put_body = _json.loads(put_request.content)
    assert put_body.get("sha") == "abc123"
    assert put_body.get("message") == "chore: update codebase snapshot [jarvis-scan]"
