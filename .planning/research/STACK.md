# Stack Research

**Domain:** AI-SDLC Jira — v1.4 Smart Architecture & Confluence Publishing
**Researched:** 2026-06-19
**Confidence:** HIGH (drawio-skill integration verdict), MEDIUM (drawpyo version pinning — latest as of research date)

---

## Verdict: What Actually Changes in v1.4

Three questions are answered below. The TL;DR for the roadmap author:

1. **drawio-skill integration** — Do NOT shell out to it from Python. Vendor the mxGraph XML-generation logic directly into `drawio_service.py` (enhanced Python string-building). No new packages required.
2. **mxGraph XML builder** — The existing hand-rolled builder in `drawio_service.py` is sufficient for MVP. `drawpyo==0.2.5` is available as an upgrade path but adds no new capability that the existing builder lacks for basic box-and-arrow diagrams. Do not add it unless layout complexity grows.
3. **Complexity classification + Confluence structuring** — No new Python packages needed. The existing `openai` SDK in Hermes plus `httpx` in the backend already cover both capabilities.

---

## Recommended Stack

### Core Technologies (unchanged)

All existing dependencies remain as-is. No additions to `backend/requirements.txt` or `hermes/requirements.txt` for the core pipeline.

| Technology | Version (pinned) | Purpose | Containers |
|------------|-----------------|---------|------------|
| FastAPI | 0.115.5 | Backend API, webhook receiver | backend |
| openai SDK | >=1.0 | freellmapi OpenAI-compat client for complexity classification LLM call | hermes |
| httpx | 0.28.1 (backend), unpinned (hermes) | Confluence REST API calls via existing ConfluenceClient | backend |
| SQLAlchemy | 2.0.36 | PipelineState persistence | backend |

### New or Changed Components in v1.4

| Component | Change | Why |
|-----------|--------|-----|
| `backend/services/drawio_service.py` | Enhance in-place — improve grid layout, add connection-direction logic | Existing hand-rolled builder is correct approach; no new deps needed |
| `backend/services/architecture_pipeline.py` | Replace with `smart_architecture_pipeline.py` — single-option flow, complexity branch | Full replacement of multi-option logic |
| `backend/services/confluence_client.py` | Update `publish_architecture` — single diagram, structured HTML, optional drawio attachment | Existing client reused; signature change only |
| `hermes/server.py` or handler | Add `@jarvis architecture` trigger routing | Reuse `HermesLLMClient.chat()` for classification call |

### Supporting Libraries (no additions required)

The complexity classification prompt is a single `HermesLLMClient.chat()` call with `temperature=0.0` — no new library. The Confluence page structuring is HTML string building — no new library.

| Library | Version | Already Present? | v1.4 Usage |
|---------|---------|-----------------|-----------|
| openai | >=1.0 | Yes (hermes) | Classification prompt: one `chat()` call, model="auto", temperature not exposed but prompt is deterministic |
| httpx | 0.28.1 | Yes (backend) | Confluence attachment upload (if chosen) |
| cryptography | 42.0.8 | Yes (backend) | Decrypt confluence_token at call time (unchanged) |

---

## drawio-skill Integration: Detailed Verdict

### What Agents365-ai/drawio-skill Actually Is

The repository is a **SKILL.md agent skill** — a plain-text instruction file consumed by AI coding agents (Claude Code, Cursor, Copilot). It is NOT:
- An HTTP service
- A Python importable library
- A CLI that can be shelled out to by Python code

Its pipeline: agent reads SKILL.md → agent writes mxGraph XML → agent shells out to **draw.io desktop application CLI** to render PNG/SVG/PDF. The draw.io desktop app (Electron-based) is a mandatory dependency for any rendering beyond raw XML delivery.

### Why Subprocess/Shell-out Does NOT Work in the Hermes Container

The drawio-skill's own documentation explicitly states: "In sandboxed environments, skip CLI export + PNG-based review steps and use the Browser fallback or deliver the `.drawio` XML only." The Hermes Docker container has no display server, no Electron runtime, and no draw.io binary. Installing the draw.io desktop app in a Docker container requires xvfb + Electron dependencies (~500MB image bloat) and significant operational complexity. The skill's own fallback for this situation is XML-only delivery — which the existing `drawio_service.py` already does.

### Recommended Integration: Vendor the XML Logic

Port the mxGraph XML-generation pattern (which the skill's inner loop produces) directly into `drawio_service.py`. The existing implementation is already correct mxGraph XML. The v1.4 improvement is to enhance the layout algorithm and add edge directionality based on component type (API Gateway → Service → Database rather than unordered grid), which is pure Python string building. This is what the drawio-skill would do if it could run — it just calls the LLM to generate the XML, then validates it.

**Why not use drawpyo instead?** `drawpyo==0.2.5` writes `.drawio` files to disk and requires reading them back. The existing approach keeps XML in memory and embeds it directly in the Confluence page body or as an attachment. For v1.4's scope (one diagram, one page), the in-memory string approach is simpler and has zero additional dependencies. Use drawpyo only if the diagram complexity grows to require auto-layout algorithms or shape-library icons.

### Confluence Diagram Embedding: What Actually Works via REST API

The draw.io Confluence Cloud macro (`<ac:structured-macro ac:name="drawio">`) requires the draw.io Marketplace plugin to be installed on the target Confluence instance to render. This cannot be assumed.

The reliable, plugin-agnostic approach is:
1. Upload the `.drawio` XML as a page attachment via `POST /wiki/rest/api/content/{id}/child/attachment`
2. Reference it with a code block or link in the page body

OR, simpler for v1.4: embed the mxGraph XML in a `<pre>` block with a link to open it in diagrams.net. The existing `confluence_client.py` already does this (`<pre class="drawio-xml">`). Enhance to add a diagrams.net viewer URL (`https://app.diagrams.net/?url=...`) if the diagram XML can be URL-encoded.

For the single-recommendation v1.4 flow, the existing HTML-body approach in `confluence_client.py` is correct. The Confluence page will include the raw XML in a code block that architects can copy into diagrams.net.

---

## Complexity Classification: Implementation Approach

The classification call routes through `HermesLLMClient.chat()` in the Hermes container (which already calls freellmapi). No new library or package.

Prompt structure for deterministic classification:
```
System: You are a software architect. Classify the following Jira ticket change as exactly one of: "small" or "complex". 
Reply with only the word "small" or the word "complex" — nothing else.

"small" = text description only needed (e.g., config change, minor refactor, single-file fix)  
"complex" = multi-component diagram needed (e.g., new service, integration, cross-system change)

Ticket: {issue_key}
Summary: {summary}
Description: {description}
```

Parse response: `response.strip().lower()` → if `"complex"`, run diagram path; else text-only. This is a 1-token classification — no structured output library (pydantic_ai, instructor, etc.) needed.

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| drawio-skill via subprocess | Requires draw.io desktop + xvfb in Docker; skill is designed for AI agent context, not Python subprocess calls | Enhanced `drawio_service.py` string builder |
| drawpyo==0.2.5 | Writes files to disk; adds dep for no capability gain at v1.4 scope | Existing in-memory mxGraph XML building |
| atlassian-python-api | Heavy SDK wrapping what `confluence_client.py` already does with httpx directly | Existing `ConfluenceClient` class |
| instructor / pydantic-ai | Overkill for a 1-token "small"/"complex" classification | Plain string parse on `response.strip().lower()` |
| rlespinasse/drawio-desktop-headless | 500MB+ Docker image; needed only for PNG/SVG export, not XML delivery | XML-only delivery to Confluence |
| tomkludy/drawio-renderer | Extra HTTP service in Docker Compose; same bloat problem | XML-only delivery |

---

## Stack Patterns by Variant

**If Confluence instance has draw.io Marketplace plugin installed:**
- Upload `.drawio` XML as page attachment via `POST /wiki/rest/api/content/{id}/child/attachment`
- Embed `<ac:structured-macro ac:name="drawio"><ac:parameter ac:name="diagramName">{filename}</ac:parameter></ac:structured-macro>` in page body storage format
- This renders the diagram natively in Confluence

**If Confluence instance does NOT have draw.io plugin (safer assumption for v1.4):**
- Embed mxGraph XML in `<pre class="drawio-xml">` code block (existing approach)
- Add a `https://app.diagrams.net/?xml=<url-encoded-xml>` link so architects can view it in-browser with one click
- No plugin dependency; works on any Confluence Cloud instance

**If diagram complexity grows beyond box-and-arrow (future milestone):**
- Add `drawpyo==0.2.5` to `backend/requirements.txt`
- Replace string-building in `drawio_service.py` with drawpyo `File`/`Page`/`Object` API
- Still deliver XML to Confluence (write to `io.BytesIO`, extract XML, same embedding approach)

---

## Installation

No new packages to install for v1.4.

```bash
# backend/requirements.txt — NO CHANGES for v1.4
# hermes/requirements.txt — NO CHANGES for v1.4

# If drawpyo is added in a future milestone:
pip install drawpyo==0.2.5   # MIT, no heavy deps, stdlib XML only
```

---

## Alternatives Considered

| Decision | Chosen | Alternative | Why Not |
|----------|--------|-------------|---------|
| drawio-skill integration | Vendor XML logic in Python | Shell out to drawio-skill scripts | Skill is an AI agent instruction file; its scripts require draw.io desktop binary |
| mxGraph XML generation | Enhanced hand-rolled string builder | drawpyo==0.2.5 | No capability gain at this scope; adds a disk-file workflow vs in-memory |
| Complexity classification | Plain `chat()` call + string parse | instructor / pydantic_ai structured outputs | 1-token response needs no schema enforcement |
| Confluence diagram embed | `<pre>` code block + diagrams.net URL | draw.io macro via attachment upload | Macro requires Marketplace plugin; can't assume it's installed |
| PNG/SVG rendering | Deferred (XML only for v1.4) | rlespinasse/drawio-desktop-headless Docker image | 500MB image, xvfb complexity, no user need for raster in v1.4 |

---

## Version Compatibility

| Package | Version | Compatibility Note |
|---------|---------|-------------------|
| openai | >=1.0 (hermes) | Hermes `HermesLLMClient` already tested against freellmapi at this version range |
| httpx | 0.28.1 (backend) | Used by `ConfluenceClient`; no change needed; attachment upload API uses same client |
| drawpyo | 0.2.5 (if added) | Python >=3.9; no conflicting deps with existing stack; MIT license |

---

## Sources

- [Agents365-ai/drawio-skill GitHub](https://github.com/Agents365-ai/drawio-skill) — confirmed: SKILL.md agent skill, not a Python library or HTTP service; XML-only mode in sandboxed environments
- [drawio-skill sandbox behavior search](https://github.com/Agents365-ai/drawio-skill/blob/main/skills/drawio-skill/SKILL.md) — confirmed: skip CLI in sandbox, deliver `.drawio` XML only
- [drawpyo on PyPI / GitHub](https://github.com/MerrimanInd/drawpyo) — v0.2.5 released Dec 28 2025; MIT; no heavy deps; writes `.drawio` files
- [drawpyo docs](https://merrimanind.github.io/drawpyo/) — confirmed: `File`/`Page`/`Object` API, disk-write workflow
- [Confluence REST API — embed draw.io via REST](https://community.developer.atlassian.com/t/how-to-embed-a-draw-io-diagram-into-a-confluence-page-through-an-api-call/91839) — confirmed: draw.io macro requires Marketplace plugin; attachment + storage format macro is the only reliable path
- [Confluence Storage Format](https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html) — XHTML-based; `ac:structured-macro` for macros
- [rlespinasse/docker-drawio-desktop-headless](https://github.com/rlespinasse/docker-drawio-desktop-headless) — confirmed: requires xvfb + Electron; justified avoidance for v1.4

---
*Stack research for: AI-SDLC Jira v1.4 — Smart Architecture & Confluence Publishing*
*Researched: 2026-06-19*
