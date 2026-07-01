"""Thin subprocess wrapper for direct Python → codebase-memory-mcp CLI calls."""
import json
import logging
import os
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

_CBM_BIN = "codebase-memory-mcp"
_CBM_TIMEOUT = 120  # seconds
_NOT_INDEXED_PHRASES = ("project not found or not indexed", "No projects indexed")
# Stable index root — persisted in the cbm-cache volume mounted at /app/cbm-cache
_INDEX_ROOT = os.environ.get("CBM_CACHE_DIR", "/app/cbm-cache/projects")


def cbm_call(tool: str, args: dict) -> dict:
    result = subprocess.run(
        [_CBM_BIN, "cli", tool, json.dumps(args)],
        capture_output=True, text=True, timeout=_CBM_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cbm {tool} failed (exit {result.returncode}): {result.stderr[:500]}")
    return json.loads(result.stdout)


def _is_not_indexed(exc: Exception) -> bool:
    return any(p in str(exc) for p in _NOT_INDEXED_PHRASES)


def _stable_project_path(github_repo: str) -> str:
    """Return a stable on-disk path for this repo's CBM index (inside the volume)."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", github_repo)
    return os.path.join(_INDEX_ROOT, safe)


def _cbm_project_name(repo_path: str) -> str:
    """Return the project name CBM derives from an absolute path.

    CBM strips the leading '/' and replaces remaining '/' with '-'.
    e.g. /app/cbm-cache/foo-bar → app-cbm-cache-foo-bar
    """
    return repo_path.lstrip("/").replace("/", "-")


def cbm_ensure_indexed(github_repo: str, github_token: str) -> str:
    """Clone repo to a stable path and index it. Returns the CBM project name.

    Skips cloning if the path already exists (index already present).
    """
    from services.repo_clone import clone_repository  # avoid circular import

    project_path = _stable_project_path(github_repo)
    project_name = _cbm_project_name(project_path)

    if not os.path.isdir(project_path):
        logger.info("CBM not indexed — cloning %s to %s", github_repo, project_path)
        os.makedirs(_INDEX_ROOT, exist_ok=True)
        cloned = clone_repository(github_repo, github_token)
        try:
            shutil.copytree(cloned.workspace_path, project_path)
        finally:
            shutil.rmtree(cloned.workspace_path, ignore_errors=True)
    else:
        logger.info("CBM reusing existing clone at %s", project_path)

    cbm_call("index_repository", {"repo_path": project_path})
    logger.info("CBM index complete for %s (project=%s)", github_repo, project_name)
    return project_name


def cbm_search_with_auto_index(query: str, limit: int, github_repo: str, github_token: str) -> dict:
    """search_graph with stable project name, auto-indexing on first use."""
    project_name = _cbm_project_name(_stable_project_path(github_repo))

    try:
        return cbm_call("search_graph", {"query": query, "limit": limit, "project": project_name})
    except Exception as exc:
        if not _is_not_indexed(exc):
            raise

    logger.info("CBM auto-indexing %s before search", github_repo)
    cbm_ensure_indexed(github_repo, github_token)
    return cbm_call("search_graph", {"query": query, "limit": limit, "project": project_name})
