"""Thin subprocess wrapper for direct Python → codebase-memory-mcp CLI calls.

Used by phases 33-36 to gather codebase context before handing off to opencode.
"""
import json
import subprocess

_CBM_BIN = "codebase-memory-mcp"
_CBM_TIMEOUT = 120  # seconds


def cbm_call(tool: str, args: dict) -> dict:
    """Run one codebase-memory-mcp CLI tool call and return parsed JSON result.

    Args:
        tool: MCP tool name, e.g. "index_repository", "search_graph".
        args: Tool arguments dict; serialised to JSON and passed as CLI arg.

    Raises:
        RuntimeError: if the subprocess exits non-zero.
        json.JSONDecodeError: if stdout is not valid JSON.
        subprocess.TimeoutExpired: if the call exceeds _CBM_TIMEOUT seconds.
    """
    result = subprocess.run(
        [_CBM_BIN, "cli", tool, json.dumps(args)],
        capture_output=True,
        text=True,
        timeout=_CBM_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cbm {tool} failed (exit {result.returncode}): {result.stderr[:500]}")
    return json.loads(result.stdout)
