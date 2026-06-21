"""Async GitHub codebase scanner — writes .hermes/codebase.md to the repo.

Threat mitigations:
  T-18-01: github_token / Authorization header NEVER passed to any logger.*
  T-18-02: tree paths treated as display strings only; no eval/exec/local FS
  T-18-03: PUT body is base64-encoded markdown only; no credentials embedded
"""

import base64
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", "out", "coverage", ".nyc_output",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "vendor", "migrations",
})

SKIP_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".docx", ".xlsx",
    ".zip", ".tar", ".gz", ".lock", ".pyc", ".pyo", ".so",
    ".db", ".sqlite", ".sqlite3", ".min.js", ".min.css",
})

MAX_FILES = 25
MAX_FILE_CHARS = 2000


def _parse_owner_repo(github_repo: str) -> tuple[str, str] | None:
    """Parse 'owner/repo' slug. Returns (owner, repo) or None if invalid."""
    if not github_repo:
        return None
    match = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", github_repo.strip())
    if not match:
        logger.warning("Invalid github_repo slug (expected owner/repo): %r", github_repo)
        return None
    return match.group(1), match.group(2)


def _skip_path(path: str) -> bool:
    """Return True if any path component is in SKIP_DIRS or extension in SKIP_EXTENSIONS."""
    parts = path.split("/")
    for part in parts:
        if part in SKIP_DIRS:
            return True
    ext = PurePosixPath(path).suffix
    if ext in SKIP_EXTENSIONS:
        return True
    name = PurePosixPath(path).name
    for skip_ext in SKIP_EXTENSIONS:
        if name.endswith(skip_ext):
            return True
    return False


def _select_key_files(all_paths: list[str]) -> list[str]:
    """Select up to MAX_FILES key paths in priority order."""
    selected: list[str] = []
    seen: set[str] = set()
    path_set = set(all_paths)

    def _add(path: str) -> None:
        if path in seen or _skip_path(path):
            return
        seen.add(path)
        selected.append(path)

    # 1. README files (any location, case-insensitive)
    for p in all_paths:
        if PurePosixPath(p).name.lower() in {"readme.md", "readme.rst", "readme.txt"}:
            _add(p)
    # 2. Root-level docker/compose
    for name in ("docker-compose.yml", "docker-compose.yaml", "Dockerfile"):
        if name in path_set:
            _add(name)
    # 3. Manifests at depth ≤ 2; Cargo.toml + go.mod at root
    for p in all_paths:
        if PurePosixPath(p).name in {"pyproject.toml", "requirements.txt", "package.json"} and p.count("/") <= 1:
            _add(p)
    for name in ("Cargo.toml", "go.mod"):
        if name in path_set:
            _add(name)
    # 4. .env files at root
    for name in (".env.example", ".env.sample"):
        if name in path_set:
            _add(name)
    # 5. Entry points at depth ≤ 1
    entry_points = {"main.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
                    "index.ts", "index.js", "main.go", "main.rs"}
    for p in all_paths:
        if PurePosixPath(p).name in entry_points and p.count("/") <= 1:
            _add(p)
    # 6. First 2 workflow YAML files
    wf_count = 0
    for p in all_paths:
        if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")):
            if wf_count < 2:
                _add(p)
                wf_count += 1
    # 7. Top-level __init__.py (depth ≤ 2)
    for p in all_paths:
        if PurePosixPath(p).name == "__init__.py" and p.count("/") <= 1:
            _add(p)
    # 8. src/index.ts, src/main.ts
    for name in ("src/index.ts", "src/main.ts"):
        if name in path_set:
            _add(name)
    # 9. Fill remaining budget
    for p in all_paths:
        if len(selected) >= MAX_FILES:
            break
        if p not in seen and not _skip_path(p):
            _add(p)

    return selected[:MAX_FILES]


def _build_ascii_tree(all_paths: list[str], max_depth: int = 3) -> str:
    """Build ASCII directory tree from flat path list, capped at max_depth."""
    def _make_node() -> dict:
        return {"__files__": [], "__dirs__": {}}

    root: dict = _make_node()
    for path in all_paths:
        parts = path.split("/")
        if any(p in SKIP_DIRS for p in parts):
            continue
        if len(parts) > max_depth:
            parts = parts[:max_depth - 1] + ["..."]
        node = root
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                node["__files__"].append(part)
            else:
                if part not in node["__dirs__"]:
                    node["__dirs__"][part] = _make_node()
                node = node["__dirs__"][part]

    lines: list[str] = ["repo-root/"]

    def _render(node: dict, prefix: str) -> None:
        entries = [(d, True) for d in sorted(node["__dirs__"])] + \
                  [(f, False) for f in sorted(node["__files__"])]
        for idx, (name, is_dir) in enumerate(entries):
            is_last = idx == len(entries) - 1
            conn = "└── " if is_last else "├── "
            child_pfx = prefix + ("    " if is_last else "│   ")
            lines.append(f"{prefix}{conn}{name}{'/' if is_dir else ''}")
            if is_dir:
                _render(node["__dirs__"][name], child_pfx)

    _render(root, "")
    return "\n".join(lines)


def _detect_tech_stack(all_paths: list[str], manifest_contents: dict[str, str]) -> list[str]:
    """Detect technology stack from file presence and manifest content."""
    stack: list[str] = []
    path_set = set(all_paths)
    if "pyproject.toml" in path_set or "setup.py" in path_set or "requirements.txt" in path_set:
        src = "pyproject.toml" if "pyproject.toml" in path_set else "requirements.txt"
        stack.append(f"Python ({src})")
    fastapi_src = manifest_contents.get("pyproject.toml", "") + manifest_contents.get("requirements.txt", "")
    if "fastapi" in fastapi_src.lower():
        stack.append("FastAPI (pyproject.toml)")
    if "manage.py" in path_set:
        stack.append("Django (manage.py)")
    if any(p.endswith("package.json") for p in all_paths):
        stack.append("Node.js (package.json)")
    if '"next"' in manifest_contents.get("package.json", ""):
        stack.append("Next.js (package.json)")
    if '"react"' in manifest_contents.get("package.json", ""):
        stack.append("React (package.json)")
    if "tsconfig.json" in path_set:
        stack.append("TypeScript (tsconfig.json)")
    if "Dockerfile" in path_set or "docker-compose.yml" in path_set:
        stack.append("Docker (Dockerfile)")
    if any(p.startswith(".github/workflows/") for p in all_paths):
        stack.append("GitHub Actions (.github/workflows/)")
    if "go.mod" in path_set:
        stack.append("Go (go.mod)")
    if "Cargo.toml" in path_set:
        stack.append("Rust (Cargo.toml)")
    return stack


def _build_module_summary(key_file_paths: list[str]) -> list[tuple[str, str]]:
    """Guess each file's purpose from its path (no file reads, pure heuristic)."""
    results: list[tuple[str, str]] = []
    for path in key_file_paths:
        lower = path.lower()
        name = PurePosixPath(path).name.lower()
        if name in {"main.py", "app.py", "index.ts", "index.js", "main.go", "main.rs"}:
            role = "Application entry point"
        elif "/tests/" in lower or "/test_" in lower or lower.startswith("test_"):
            role = "Test module"
        elif path.startswith("backend/"):
            role = "Backend service module"
        elif path.startswith("frontend/") or path.startswith("src/"):
            role = "Frontend source file"
        elif name in {"readme.md", "readme.rst", "readme.txt"}:
            role = "Project documentation"
        elif name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
            role = "Container configuration"
        elif name in {"pyproject.toml", "requirements.txt", "package.json", "cargo.toml", "go.mod"}:
            role = "Dependency manifest"
        else:
            role = "Source file"
        results.append((path, role))
    return results


def _build_markdown(
    owner: str,
    repo: str,
    stack: list[str],
    tree: str,
    key_file_contents: dict[str, str],
    module_summary: list[tuple[str, str]],
    files_read: int,
) -> str:
    """Assemble final markdown. T-18-03: no credentials embedded."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# Codebase Snapshot: {owner}/{repo}",
        "",
        f"_Generated {today_str} by Jarvis. Do not edit manually — overwritten on each scan._",
        "",
        "## Tech Stack",
        "",
    ]
    lines += [f"- {item}" for item in stack] if stack else ["No manifest files detected."]
    lines += [
        "",
        "## Directory Structure",
        "",
        "```",
        tree,
        "```",
        "",
        "## Key Files",
        "",
    ]
    for path, content in key_file_contents.items():
        lines += [f"### {path}", f"> {content[:MAX_FILE_CHARS]}", ""]
    lines += [
        "## Module Summary",
        "",
        "| Path | Role |",
        "|------|------|",
    ]
    lines += [f"| {p} | {r} |" for p, r in module_summary]
    lines += ["", f"_Files read: {files_read}. Scan completed: {now_iso}_"]
    return "\n".join(lines)


async def run(
    github_repo: str,
    github_token: str,
    project_id: int,
    db: Session,
) -> None:
    """Scan a GitHub repo and commit a snapshot to .hermes/codebase.md.

    T-18-01: github_token NEVER logged.
    T-18-02: all GitHub API paths/content treated as display data.
    T-18-03: PUT body is base64-encoded markdown only.
    """
    api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)
    parsed = _parse_owner_repo(github_repo)
    if parsed is None:
        logger.warning("run() called with invalid github_repo slug — aborting scan")
        return
    owner, repo = parsed

    # T-18-01: header value never logged
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        # Step 4: Get default branch
        repo_resp = await client.get(f"{api_base}/repos/{owner}/{repo}")
        if repo_resp.status_code != 200:
            logger.warning("Repo metadata fetch failed for %s/%s (status %s)", owner, repo, repo_resp.status_code)
            raise RuntimeError(
                f"Repo metadata fetch failed for {owner}/{repo} (status {repo_resp.status_code})"
            )
        default_branch = repo_resp.json().get("default_branch", "main")

        # Step 5: Get recursive tree
        trees_resp = await client.get(f"{api_base}/repos/{owner}/{repo}/git/trees/HEAD", params={"recursive": "1"})
        if trees_resp.status_code != 200:
            logger.warning("Trees API failed for %s/%s (status %s)", owner, repo, trees_resp.status_code)
            raise RuntimeError(
                f"Trees API failed for {owner}/{repo} (status {trees_resp.status_code})"
            )
        trees_data = trees_resp.json()
        if trees_data.get("truncated"):
            logger.warning("Trees API truncated for %s/%s — snapshot may be incomplete", owner, repo)

        # Step 6: Extract blob paths
        all_paths: list[str] = [
            item["path"] for item in trees_data.get("tree", []) if item.get("type") == "blob"
        ]

        # Steps 7-8: Select + fetch key files
        selected = _select_key_files(all_paths)
        key_file_contents: dict[str, str] = {}
        manifest_contents: dict[str, str] = {}
        manifest_names = {"pyproject.toml", "requirements.txt", "package.json"}

        for path in selected:
            resp = await client.get(f"{api_base}/repos/{owner}/{repo}/contents/{path}")
            if resp.status_code in (404, 403):
                logger.warning("Skipping %s/%s/%s (status %s)", owner, repo, path, resp.status_code)
                continue
            if resp.status_code != 200:
                logger.warning("Unexpected status %s fetching %s/%s/%s", resp.status_code, owner, repo, path)
                continue
            raw_text = base64.b64decode(resp.json().get("content", "")).decode("utf-8", errors="replace")
            key_file_contents[path] = raw_text[:MAX_FILE_CHARS]
            name = PurePosixPath(path).name
            if name in manifest_names:
                manifest_contents[name] = raw_text[:MAX_FILE_CHARS]

        # Steps 9-12: Build outputs
        stack = _detect_tech_stack(all_paths, manifest_contents)
        tree = _build_ascii_tree(all_paths)
        module_summary = _build_module_summary(list(key_file_contents.keys()))
        markdown = _build_markdown(owner, repo, stack, tree, key_file_contents, module_summary, len(key_file_contents))

        # Step 13: Idempotency GET — fetch existing sha
        existing_sha: str | None = None
        sha_resp = await client.get(f"{api_base}/repos/{owner}/{repo}/contents/.hermes/codebase.md")
        if sha_resp.status_code == 200:
            existing_sha = sha_resp.json().get("sha")

        # Step 14: PUT to commit or update
        put_body: dict = {
            "message": "chore: update codebase snapshot [jarvis-scan]",
            "content": base64.b64encode(markdown.encode()).decode(),
            "branch": default_branch,
        }
        if existing_sha is not None:
            put_body["sha"] = existing_sha

        put_resp = await client.put(
            f"{api_base}/repos/{owner}/{repo}/contents/.hermes/codebase.md",
            json=put_body,
        )
        if put_resp.status_code not in (200, 201):
            # T-18-01: do NOT log github_token or Authorization header value
            logger.warning("PUT .hermes/codebase.md failed for %s/%s (status %s)", owner, repo, put_resp.status_code)
            raise RuntimeError(f"GitHub Contents PUT failed with status {put_resp.status_code} for {owner}/{repo}/.hermes/codebase.md")

        # Step 15: T-18-01: log only owner/repo + file count
        logger.info("Codebase snapshot committed to %s/%s/.hermes/codebase.md (files_read=%d)", owner, repo, len(key_file_contents))
