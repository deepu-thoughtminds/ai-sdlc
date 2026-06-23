# qa-sandbox: ephemeral QA toolchain image invoked per-command via docker run --rm
#
# Python tools: ruff (lint), mypy (type check), bandit (security scan)
# JS/TS tools:  eslint, typescript (tsc)
# git included so static analysis tools can inspect .git metadata
#
# Usage (backend calls this pattern — never a long-lived container):
#   docker run --rm -v {workspace}:/workspace qa-sandbox ruff check /workspace
#   docker run --rm -v {workspace}:/workspace qa-sandbox tsc --noEmit --project /workspace/tsconfig.json
#   docker run --rm -v {workspace}:/workspace qa-sandbox eslint /workspace --ext .ts,.tsx,.js,.jsx
#
# No CMD — backend supplies full command at docker run invocation.
# No ENTRYPOINT — keep default /bin/bash for ad-hoc inspection.

FROM python:3.12-slim

# Install system dependencies: git + Node.js (nodejs + npm from nodesource)
# Using nodesource to get a recent LTS node; bookworm backports not always available.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python QA tools
RUN pip install --no-cache-dir \
    ruff \
    mypy \
    bandit

# Install JS/TS QA tools globally
RUN npm install -g \
    eslint \
    typescript

# Set working directory (backend mounts workspace here)
WORKDIR /workspace
