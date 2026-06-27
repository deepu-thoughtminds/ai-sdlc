"""
Smoke test for real freellmapi integration.
Skipped automatically when FREELLMAPI_API_KEY is not set.
Run manually: FREELLMAPI_API_KEY=<key> python3 -m pytest tests/test_smoke_freellmapi.py -v -s
"""
import os
import pytest
import httpx

FREELLMAPI_API_KEY = os.getenv("FREELLMAPI_API_KEY", "")
FREELLMAPI_BASE_URL = os.getenv("FREELLMAPI_BASE_URL", "http://localhost:3001")

# FREELLMAPI_BASE_URL may or may not carry the OpenAI-compat "/v1" suffix (the
# backend sets it WITH /v1). The health endpoint lives at the service root
# (/api/ping); chat completions live under /v1. Normalise both so the smoke
# test works regardless of which form the env var takes.
_ROOT = FREELLMAPI_BASE_URL.rstrip("/")
if _ROOT.endswith("/v1"):
    _ROOT = _ROOT[: -len("/v1")]
_V1 = _ROOT + "/v1"

requires_freellmapi = pytest.mark.skipif(
    not FREELLMAPI_API_KEY,
    reason="FREELLMAPI_API_KEY not set — skipping live integration test"
)


@requires_freellmapi
def test_freellmapi_health():
    """freellmapi /api/ping returns 200."""
    response = httpx.get(f"{_ROOT}/api/ping", timeout=10)
    assert response.status_code == 200


@requires_freellmapi
def test_freellmapi_chat_completions():
    """freellmapi /v1/chat/completions returns a non-empty response."""
    response = httpx.post(
        f"{_V1}/chat/completions",
        headers={"Authorization": f"Bearer {FREELLMAPI_API_KEY}"},
        json={"model": "auto", "messages": [{"role": "user", "content": "Say 'pong' and nothing else."}]},
        timeout=30,
    )
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    content = data["choices"][0]["message"]["content"]
    assert content and len(content) > 0


@requires_freellmapi
def test_llm_router_heavy_stage_integration():
    """llm_router.route_request for a heavy stage returns non-stub content."""
    import sys
    sys.path.insert(0, ".")
    from services.llm_router import route_request, HEAVY_STAGES

    assert "describe" in HEAVY_STAGES
    result = route_request("describe", "In one word, what is Python?")
    assert result.provider == "freellmapi"
    assert result.content not in ("", "[LLM unavailable]", "[stub]")
