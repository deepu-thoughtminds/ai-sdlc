"""Unit tests for services.test_generator — TESTGEN-01.

Tests (5 total):
1. test_parse_file_changes_returns_file_change_list — _parse_file_changes (imported
   from code_generator) returns a list[FileChange] given a single ### FILE: block.
2. test_generate_unit_tests_calls_route_request_once — generate_unit_tests() calls
   route_request("testgen", prompt) exactly once; assert prompt contains issue_key,
   relevant_file path, and codebase_context string.
3. test_generate_unit_tests_stub_response_returns_empty — route_request returns
   LLMResponse(content="[stub]") -> empty list (graceful degradation).
4. test_generate_unit_tests_none_or_empty_codebase_context_no_raise — codebase_context
   None or "" -> prompt builds successfully, no exception raised.
5. test_generate_unit_tests_prompt_contains_tests_and_pytest — prompt text contains
   "tests/" and "pytest" substrings (plan-level instruction check).

No real LLM calls occur — route_request is patched at services.test_generator.route_request.
"""

from unittest.mock import patch

import pytest

from services.code_generator import FileChange, _parse_file_changes
from services.llm_router import LLMResponse
from services.test_generator import generate_unit_tests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    """Build a mock LLMResponse with given content."""
    return LLMResponse(provider="freellmapi", content=content, model="auto")


SAMPLE_TEST_FILE_OUTPUT = """\
### FILE: tests/test_foo.py
```python
import pytest
from foo import bar

def test_bar_returns_true():
    assert bar() is True
```
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_file_changes_returns_file_change_list():
    """_parse_file_changes given a single ### FILE: tests/test_foo.py block
    returns a list with one FileChange with path 'tests/test_foo.py'.
    """
    result = _parse_file_changes(SAMPLE_TEST_FILE_OUTPUT)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], FileChange)
    assert result[0].path == "tests/test_foo.py"
    assert "def test_bar_returns_true" in result[0].content


def test_generate_unit_tests_calls_route_request_once():
    """generate_unit_tests() calls route_request("testgen", prompt) exactly once.

    The prompt must contain:
    - the issue_key ("PROJ-42")
    - the relevant_file path ("src/main.py")
    - the codebase_context string ("MyApp module summary")
    """
    captured_calls = []

    def capture(stage, prompt):
        captured_calls.append((stage, prompt))
        return _make_llm_response("[stub]")

    with patch("services.test_generator.route_request", side_effect=capture):
        generate_unit_tests(
            issue_key="PROJ-42",
            issue_summary="Add unit tests",
            issue_description="Generate tests for main module.",
            codebase_context="MyApp module summary",
            relevant_file_contents={"src/main.py": "def run(): pass"},
        )

    assert len(captured_calls) == 1, f"Expected 1 call, got {len(captured_calls)}"
    stage, prompt = captured_calls[0]
    assert stage == "testgen", f"Expected stage='testgen', got {stage!r}"
    assert "PROJ-42" in prompt, "issue_key not found in prompt"
    assert "src/main.py" in prompt, "relevant file path not found in prompt"
    assert "MyApp module summary" in prompt, "codebase_context not found in prompt"


def test_generate_unit_tests_stub_response_returns_empty():
    """route_request returns LLMResponse(content='[stub]') -> empty list.

    Graceful degradation (T-06-02 style): generate_unit_tests must not raise
    and must return [] when the LLM returns a stub/empty response.
    """
    with patch(
        "services.test_generator.route_request",
        return_value=_make_llm_response("[stub]"),
    ):
        result = generate_unit_tests(
            issue_key="PROJ-1",
            issue_summary="test",
            issue_description="test desc",
            codebase_context="some context",
            relevant_file_contents={"src/foo.py": "def foo(): pass"},
        )

    assert result == [], f"Expected [], got {result!r}"


def test_generate_unit_tests_none_or_empty_codebase_context_no_raise():
    """codebase_context=None or '' -> prompt builds without error; no exception raised.

    Ensures None is never concatenated into the prompt string (would raise TypeError).
    """
    for ctx in (None, ""):
        with patch(
            "services.test_generator.route_request",
            return_value=_make_llm_response("[stub]"),
        ):
            # Must not raise TypeError or AttributeError
            result = generate_unit_tests(
                issue_key="PROJ-10",
                issue_summary="test",
                issue_description="desc",
                codebase_context=ctx,
                relevant_file_contents={"src/foo.py": "def foo(): pass"},
            )
        # Stub response -> empty list
        assert result == [], f"Expected [] for ctx={ctx!r}, got {result!r}"


def test_generate_unit_tests_prompt_contains_tests_and_pytest():
    """Prompt must contain 'tests/' and 'pytest' substrings.

    The plan requires the prompt instructs the LLM to prefix generated test
    file paths with 'tests/' and to use pytest conventions.
    """
    captured_prompts: list[str] = []

    def capture(stage, prompt):
        captured_prompts.append(prompt)
        return _make_llm_response("[stub]")

    with patch("services.test_generator.route_request", side_effect=capture):
        generate_unit_tests(
            issue_key="PROJ-5",
            issue_summary="test generation",
            issue_description="generate pytest tests",
            codebase_context="Small app",
            relevant_file_contents={"src/app.py": "def main(): pass"},
        )

    assert captured_prompts, "route_request was never called"
    prompt = captured_prompts[0]
    assert "tests/" in prompt, f"'tests/' not found in prompt"
    assert "pytest" in prompt, f"'pytest' not found in prompt"


# ---------------------------------------------------------------------------
# Phase 26-01 RED: generate_e2e_tests() — TESTGEN-03
# ---------------------------------------------------------------------------


def test_generate_e2e_tests_calls_route_request_once():
    """generate_e2e_tests calls route_request once with stage='testgen'."""
    from services.test_generator import generate_e2e_tests

    with patch(
        "services.test_generator.route_request",
        return_value=_make_llm_response(
            "### FILE: tests/e2e/test_login.spec.ts\n```typescript\ntest('ok', () => {});\n```"
        ),
    ) as mock_route:
        result = generate_e2e_tests(
            issue_key="PROJ-1",
            issue_summary="Login feature",
            issue_description="desc",
            codebase_context="context",
            relevant_file_contents={"src/login.ts": "export function login() {}"},
        )

    mock_route.assert_called_once()
    stage, _ = mock_route.call_args[0]
    assert stage == "testgen"
    assert len(result) == 1


def test_generate_e2e_tests_stub_response_returns_empty():
    """Stub/empty LLM response returns []."""
    from services.test_generator import generate_e2e_tests

    with patch(
        "services.test_generator.route_request",
        return_value=_make_llm_response("[stub]"),
    ):
        result = generate_e2e_tests(
            issue_key="PROJ-1",
            issue_summary="test",
            issue_description="desc",
            codebase_context=None,
            relevant_file_contents={},
        )

    assert result == []


def test_generate_e2e_tests_prompt_contains_playwright_and_e2e_path():
    """Prompt contains 'Playwright' and 'e2e/' substrings."""
    from services.test_generator import generate_e2e_tests

    captured: list[str] = []

    def capture(stage, prompt):
        captured.append(prompt)
        return _make_llm_response("[stub]")

    with patch("services.test_generator.route_request", side_effect=capture):
        generate_e2e_tests(
            issue_key="PROJ-5",
            issue_summary="E2E tests",
            issue_description="run playwright",
            codebase_context="app",
            relevant_file_contents={},
        )

    assert captured, "route_request was never called"
    prompt = captured[0]
    assert "Playwright" in prompt or "playwright" in prompt.lower(), f"'Playwright' not in prompt"
    assert "e2e/" in prompt or "e2e\\" in prompt, f"'e2e/' not found in prompt"
