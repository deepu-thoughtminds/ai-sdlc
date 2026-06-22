---
status: complete
quick_id: 260622-p0f
date: 2026-06-22
commit: d644c8e
---

# Quick Task 260622-p0f: Replace graphify with codebase-memory-mcp

## What changed

### backend/Dockerfile
Added Node.js + npm installation and:
- `npm install -g codebase-memory-mcp@0.8.1` — installs the static binary MCP server
- `mkdir -p /root/.claude && printf '{"mcpServers":...}' > /root/.claude/.mcp.json` — registers codebase-memory-mcp as a stdio MCP server so the claude CLI subprocess picks it up automatically

### backend/services/claude_code_executor.py
Updated module docstring and the claude CLI prompt:
- Removed: `1. Run /graphify update .` (LLM-based codebase indexing)
- Removed: `2. Run /gsd-graphify plan` (graphify-based planning)
- Added: Step 1 — call `index_repository('.')` via codebase-memory-mcp (no LLM)
- Added: Step 2 — use `search_graph` and `get_code_snippet` to understand code structure
- Kept: Step 3 — `/gsd-quick` for planning and implementation

## Why

graphify required LLM calls to index the codebase, making it slow and expensive. codebase-memory-mcp uses tree-sitter for static analysis — zero LLM calls, faster indexing, same rich code intelligence (call graphs, symbol search, snippet extraction).

## Commit

d644c8e — feat(dev-pipeline): replace graphify with codebase-memory-mcp for codebase indexing
