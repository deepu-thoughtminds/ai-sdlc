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

FROM node:20-slim AS node-base

FROM python:3.12-slim

# Install system dependencies: git (Node.js copied from node-base stage below
# instead of curl|bash nodesource install — avoids executing an unverified
# remote script at build time).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node-base /usr/local /usr/local

# Install Python QA tools (pinned for reproducible builds)
RUN pip install --no-cache-dir \
    "ruff==0.4.7" \
    "mypy==1.10.0" \
    "bandit==1.7.9" \
    "pytest==8.2.2" \
    "pytest-playwright==0.5.1"

# Install Playwright browsers (chromium only — sufficient for evaluation tests)
RUN playwright install --with-deps chromium

# Install JS/TS QA tools globally; yarn ships with node:20, add pnpm for pnpm repos
RUN npm install -g --force \
    "eslint@8.57.0" \
    "typescript@5.4.5" \
    "pnpm" \
    "@playwright/test"

# Install Chromium for Node.js @playwright/test (may reuse the binary above if versions match;
# downloads its own versioned copy to ~/.cache/ms-playwright/ otherwise).
# ponytail: system deps (libglib etc.) already present from the Python playwright install above.
RUN playwright install chromium

# Set working directory (backend mounts workspace here)
WORKDIR /workspace
