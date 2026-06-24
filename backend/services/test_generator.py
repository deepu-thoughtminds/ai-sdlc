"""Test generation service — TESTGEN-01.

Builds a structured prompt from the Jira issue, codebase snapshot context,
and relevant file contents, then calls freellmapi via route_request('testgen', ...)
to generate pytest unit test files.

The LLM is prompted to respond with structured sections using the convention:
  ### FILE: tests/path/to/test_foo.py
  ```python
  <full test file content>
  ```

This module reuses FileChange and _parse_file_changes directly from
code_generator.py — the established ### FILE: convention referenced by TESTGEN-01.
No duplicate regex parser is defined here.

Threat mitigations:
  T-24-02: Prompt contains only issue_key/summary/description/codebase_context/
            relevant_file_contents — no token or credential values interpolated.
            Only issue/codebase/file content parameters are accepted by
            generate_unit_tests(); credentials are never passed in or forwarded.
  T-06-02 (shared): Graceful fallback on empty/stub LLM output — returns []
            rather than raising, so callers can post a "no unit tests generated"
            comment (mirrors code_generator.py's contract).
"""

import logging

from services.code_generator import FileChange, _parse_file_changes
from services.llm_router import route_request

logger = logging.getLogger(__name__)


def generate_unit_tests(
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    codebase_context: str | None,
    relevant_file_contents: dict[str, str],
) -> list[FileChange]:
    """Generate pytest unit test files for a Jira issue via freellmapi.

    TESTGEN-01: Given a Jira issue, codebase snapshot context, and relevant
    file contents, calls freellmapi (testgen stage) and receives parsed
    file-level test changes using the ### FILE: convention.

    T-24-02: Only issue_key/summary/description/codebase_context/
    relevant_file_contents are interpolated into the prompt — no token or
    credential values are ever passed into this function or forwarded to
    the LLM prompt.

    Args:
        issue_key:              Jira issue key (e.g. "PROJ-42").
        issue_summary:          Issue summary field.
        issue_description:      Issue description (plain text).
        codebase_context:       Codebase snapshot from .hermes/codebase.md
                                (plain text or markdown). May be None or ""
                                — safe to pass as-is; falsy values produce
                                an empty Codebase context section (never
                                concatenate None directly into the prompt).
        relevant_file_contents: Mapping of relative file path → file content
                                for files in the cloned workspace that are
                                relevant to the issue. Used to ground tests
                                in actual code rather than fabricated APIs.

    Returns:
        List of FileChange instances (may be empty if LLM returns no parseable
        test files — callers should handle this as "no unit tests generated").
    """
    logger.info("Generating unit tests for ticket %s", issue_key)

    # Build relevant file blocks (same pattern as code_generator.generate_code_changes)
    if relevant_file_contents:
        file_blocks = "\n\n".join(
            f"### {path}\n{content}" for path, content in relevant_file_contents.items()
        )
        file_contents_section = (
            "Relevant file contents (READ THESE before writing tests):\n\n"
            f"{file_blocks}\n\n"
        )
    else:
        file_contents_section = ""

    # T-24-02: use empty string when codebase_context is falsy — never concatenate None
    codebase_section = codebase_context or ""

    # T-24-02: prompt contains only issue data + codebase context + file content
    prompt = (
        "You are a senior software engineer writing pytest unit tests for a Jira story. "
        "Write ONLY unit tests — do not modify source files.\n\n"
        f"Jira Ticket: {issue_key}\n"
        f"Summary: {issue_summary}\n"
        f"Description:\n{issue_description}\n\n"
        "Codebase context:\n"
        f"{codebase_section}\n\n"
        f"{file_contents_section}"
        "IMPORTANT: Respond with ONLY the test file(s) needed. "
        "For each test file, use EXACTLY this format:\n\n"
        "### FILE: tests/path/to/test_module.py\n"
        "```python\n"
        "<complete test file content here>\n"
        "```\n\n"
        "Rules:\n"
        "- Prefix every generated test file path with tests/ (e.g. tests/test_foo.py)\n"
        "- Use pytest conventions: def test_...() functions, assert statements, "
        "no unittest.TestCase\n"
        "- Write tests ONLY for behaviour visible in the supplied file contents — "
        "do not fabricate APIs or functions not present in the code\n"
        "- Include complete file content for each test file\n"
        "- Use the exact ### FILE: format for each test file\n"
        "- Do not include explanations outside of the file blocks"
    )

    route_result = route_request("testgen", prompt)
    return _parse_file_changes(route_result.content)


def generate_e2e_tests(
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    codebase_context: str | None,
    relevant_file_contents: dict[str, str],
) -> list[FileChange]:
    """Generate Playwright E2E test files for a Jira issue via freellmapi.

    TESTGEN-03: Generates Playwright TypeScript spec files using the same
    ### FILE: convention as generate_unit_tests(). Returns [] when the LLM
    returns no parseable test files.

    T-26-02: Callers must gate invocation on playwright.config.* detection.
    T-24-02 (shared): Only issue_key/summary/description/codebase_context/
    relevant_file_contents are interpolated — no credentials forwarded.
    """
    logger.info("Generating E2E tests for ticket %s", issue_key)

    if relevant_file_contents:
        file_blocks = "\n\n".join(
            f"### {path}\n{content}" for path, content in relevant_file_contents.items()
        )
        file_contents_section = (
            "Relevant file contents (READ THESE before writing tests):\n\n"
            f"{file_blocks}\n\n"
        )
    else:
        file_contents_section = ""

    codebase_section = codebase_context or ""

    prompt = (
        "You are a senior software engineer writing Playwright E2E tests for a Jira story. "
        "Write ONLY Playwright TypeScript test files — do not modify source files.\n\n"
        f"Jira Ticket: {issue_key}\n"
        f"Summary: {issue_summary}\n"
        f"Description:\n{issue_description}\n\n"
        "Codebase context:\n"
        f"{codebase_section}\n\n"
        f"{file_contents_section}"
        "IMPORTANT: Respond with ONLY the test file(s) needed. "
        "For each test file, use EXACTLY this format:\n\n"
        "### FILE: tests/e2e/path/to/test.spec.ts\n"
        "```typescript\n"
        "<complete test file content here>\n"
        "```\n\n"
        "Rules:\n"
        "- Prefix every generated test file path with e2e/ or tests/e2e/\n"
        "- Use Playwright test conventions: test(), expect() from @playwright/test\n"
        "- Write tests ONLY for behaviour visible in the supplied file contents\n"
        "- Include complete file content for each test file\n"
        "- Use the exact ### FILE: format for each test file\n"
        "- Do not include explanations outside of the file blocks"
    )

    route_result = route_request("testgen", prompt)
    return _parse_file_changes(route_result.content)
