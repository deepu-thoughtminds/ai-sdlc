"""Unit tests for services.cbm_client.cbm_call.

Tests:
1. test_cbm_call_parses_json_stdout — subprocess invoked with expected argv,
   stdout JSON parsed and returned.
2. test_cbm_call_raises_on_nonzero_exit — non-zero exit raises RuntimeError
   including the exit code.

subprocess.run is patched in all tests — no real codebase-memory-mcp binary
invocation occurs.
"""

import json
from unittest.mock import MagicMock, patch

from services.cbm_client import cbm_call


def test_cbm_call_parses_json_stdout():
    fake_result = {"nodes": [{"id": "main"}]}
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = json.dumps(fake_result)
    mock.stderr = ""
    with patch("services.cbm_client.subprocess.run", return_value=mock) as p:
        result = cbm_call("search_graph", {"query": "main", "limit": 5})
    p.assert_called_once_with(
        ["codebase-memory-mcp", "cli", "search_graph", '{"query": "main", "limit": 5}'],
        capture_output=True, text=True, timeout=120,
    )
    assert result == fake_result


def test_cbm_call_raises_on_nonzero_exit():
    mock = MagicMock()
    mock.returncode = 1
    mock.stdout = ""
    mock.stderr = "error: repo not found"
    with patch("services.cbm_client.subprocess.run", return_value=mock):
        try:
            cbm_call("index_repository", {"repo_path": "/nonexistent"})
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "exit 1" in str(e)
