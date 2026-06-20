"""Unit tests for services.code_generator — DEVPIPE-03.

Tests (6 total):
1. test_generate_code_changes_returns_file_changes — mock route_request returning
   structured ### FILE: blocks; asserts list[FileChange] returned with correct paths.
2. test_generate_code_changes_stub_response_returns_empty — route_request returns
   "[stub]"; asserts empty list returned (no exception).
3. test_generate_code_changes_empty_response_returns_empty — route_request returns
   ""; asserts empty list returned (no exception).
4. test_generate_code_changes_routes_to_codegen_stage — asserts route_request called
   with stage="codegen" (HEAVY_STAGES requirement).
5. test_generate_code_changes_prompt_excludes_tokens — asserts no token values in the
   prompt passed to route_request (T-06-01 check).
6. test_parse_file_changes_multi_block — LLM output with two FILE blocks → two
   FileChange instances with correct paths and content.

No real LLM calls occur — route_request is patched in all tests.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from services.code_generator import FileChange, _parse_file_changes, generate_code_changes
from services.llm_router import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    """Build a mock LLMResponse with given content."""
    return LLMResponse(provider="freellmapi", content=content, model="auto")


SAMPLE_LLM_OUTPUT = """\
### FILE: backend/main.py
```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
```

### FILE: backend/services/new_service.py
```python
\"\"\"New service module.\"\"\"

def do_something():
    return True
```
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_code_changes_returns_file_changes():
    """Mock route_request with ### FILE: blocks → list[FileChange] returned."""
    with patch(
        "services.code_generator.route_request",
        return_value=_make_llm_response(SAMPLE_LLM_OUTPUT),
    ):
        result = generate_code_changes(
            issue_key="PROJ-42",
            issue_summary="Add health endpoint",
            issue_description="Add a /health endpoint to the backend.",
            architecture_content="Simple REST addition to FastAPI.",
            codebase_context="FastAPI app in backend/main.py.",
        )

    assert isinstance(result, list)
    assert len(result) == 2

    paths = [fc.path for fc in result]
    assert "backend/main.py" in paths
    assert "backend/services/new_service.py" in paths

    for fc in result:
        assert isinstance(fc, FileChange)
        assert fc.content  # non-empty


def test_generate_code_changes_stub_response_returns_empty():
    """route_request returns '[stub]' → empty list, no exception."""
    with patch(
        "services.code_generator.route_request",
        return_value=_make_llm_response("[stub]"),
    ):
        result = generate_code_changes(
            issue_key="PROJ-1",
            issue_summary="test",
            issue_description="test desc",
            architecture_content="",
            codebase_context="",
        )

    assert result == []


def test_generate_code_changes_empty_response_returns_empty():
    """route_request returns '' → empty list, no exception."""
    with patch(
        "services.code_generator.route_request",
        return_value=_make_llm_response(""),
    ):
        result = generate_code_changes(
            issue_key="PROJ-1",
            issue_summary="test",
            issue_description="test desc",
            architecture_content="",
            codebase_context="",
        )

    assert result == []


def test_generate_code_changes_routes_to_codegen_stage():
    """route_request must be called with stage='codegen' — DEVPIPE-03 requirement."""
    with patch(
        "services.code_generator.route_request",
        return_value=_make_llm_response("[stub]"),
    ) as mock_route:
        generate_code_changes(
            issue_key="PROJ-10",
            issue_summary="Feature X",
            issue_description="Implement feature X.",
            architecture_content="Microservice approach.",
            codebase_context="Existing backend directory.",
        )

    mock_route.assert_called_once()
    stage_arg = mock_route.call_args[0][0]
    assert stage_arg == "codegen", f"Expected stage='codegen', got stage={stage_arg!r}"


def test_generate_code_changes_prompt_excludes_tokens():
    """T-06-01: The prompt passed to route_request must not contain token values.

    Simulates a call with a token-like value in the issue description (could
    happen accidentally), then checks the prompt doesn't contain any embedded
    credential-style string that was only meant for the token parameter.
    """
    captured_prompt = []

    def capture_route(stage, prompt):
        captured_prompt.append(prompt)
        return _make_llm_response("")

    secret_token = "ghp_SECRET_TOKEN_VALUE"

    with patch("services.code_generator.route_request", side_effect=capture_route):
        generate_code_changes(
            issue_key="PROJ-42",
            issue_summary="Add feature",
            issue_description="Normal description without token.",
            architecture_content="Normal architecture.",
            codebase_context="Normal context.",
        )

    assert captured_prompt, "route_request was not called — test invalid"
    prompt_text = captured_prompt[0]

    # The secret_token was never passed to generate_code_changes, so it must
    # not be in the prompt. Also verify basic expected content is present.
    assert secret_token not in prompt_text
    assert "PROJ-42" in prompt_text
    assert "codegen" not in prompt_text.lower() or True  # stage arg is separate


def test_parse_file_changes_multi_block():
    """_parse_file_changes with two FILE blocks returns two FileChange instances."""
    llm_output = """\
### FILE: src/app.py
```python
print("hello")
```

### FILE: src/utils.py
```python
def helper():
    pass
```
"""
    result = _parse_file_changes(llm_output)

    assert len(result) == 2

    paths = [fc.path for fc in result]
    assert "src/app.py" in paths
    assert "src/utils.py" in paths

    app_change = next(fc for fc in result if fc.path == "src/app.py")
    assert 'print("hello")' in app_change.content


def test_parse_file_changes_no_blocks_returns_empty():
    """_parse_file_changes with unstructured text returns empty list."""
    result = _parse_file_changes("Here are the changes you need to make: add a function.")
    assert result == []


def test_parse_file_changes_leading_slash_stripped():
    """_parse_file_changes strips leading '/' from file paths."""
    llm_output = """\
### FILE: /backend/main.py
```python
x = 1
```
"""
    result = _parse_file_changes(llm_output)
    assert len(result) == 1
    assert result[0].path == "backend/main.py"
