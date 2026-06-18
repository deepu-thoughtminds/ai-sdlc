<!-- GSD:project-start source:PROJECT.md -->

## Project

**AI-SDLC Jira**

An agentic AI platform that augments the Jira Scrum pipeline by embedding a Hermes agent into the Jira comment history. Team members trigger the agent via `@agent-name` mentions in Jira comments, and it automates SDLC stages: elaborating feature descriptions, generating architecture diagrams, making code changes, and running QA — all surfaced back into the ticket's comment history.

**Core Value:** Team members trigger AI-powered SDLC automation directly from Jira comment history, with every output (descriptions, architecture, PRs, test results) linked back to the originating ticket.

### Constraints

- **Tech Stack:** Python (FastAPI) backend + Next.js frontend + Docker Compose for service orchestration
- **LLM Cost:** freellmapi used for all heavy tasks to minimize API costs; must integrate with freellmapi Docker service
- **Integration:** Jira MCP, Confluence MCP, GitHub API/MCP required; drawio skill from Agents365-ai/drawio-skill
- **Security:** Project credentials must be encrypted at rest in DB; never logged or exposed in API responses
- **Autonomy:** Dev stage is fully autonomous code changes — requires robust codebase reading and PR creation

<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->

## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
