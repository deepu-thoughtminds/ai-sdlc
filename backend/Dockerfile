FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm docker-cli && rm -rf /var/lib/apt/lists/*

# Install codebase-memory-mcp so claude CLI can use it as a stdio MCP server
# for LLM-free codebase indexing (replaces graphify which required LLM).
RUN npm install -g codebase-memory-mcp@0.8.1

# Register codebase-memory-mcp with the claude CLI as a global stdio MCP server.
RUN mkdir -p /root/.claude && printf '{"mcpServers":{"codebase-memory-mcp":{"command":"codebase-memory-mcp","args":[],"type":"stdio"}}}\n' > /root/.claude/.mcp.json

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
