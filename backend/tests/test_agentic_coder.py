"""Unit tests for services.agentic_coder._opencode_config.

Tests:
1. test_opencode_config_has_mcp — config JSON registers codebase-memory-mcp
   as a local opencode MCP server.
2. test_opencode_config_includes_api_key — OPENCODE_API_KEY env var flows
   into provider.opencode.options.apiKey.
"""

import json

from services.agentic_coder import _opencode_config


def test_opencode_config_has_mcp(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    config = json.loads(_opencode_config())
    assert "mcp" in config
    assert "codebase-memory-mcp" in config["mcp"]
    mcp_entry = config["mcp"]["codebase-memory-mcp"]
    assert mcp_entry["type"] == "local"
    assert mcp_entry["command"] == ["codebase-memory-mcp"]


def test_opencode_config_includes_api_key(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "my-test-key")
    config = json.loads(_opencode_config())
    assert config["provider"]["opencode"]["options"]["apiKey"] == "my-test-key"
