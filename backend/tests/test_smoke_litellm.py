"""
Smoke test for LiteLLM/gpt-4.1-mini integration.
Skipped automatically when OPENAI_API_KEY is not set.
Run manually: OPENAI_API_KEY=<key> python3 -m pytest tests/test_smoke_litellm.py -v -s
"""
import os
import pytest
import httpx

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "sk-litellm-local")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

requires_openai = pytest.mark.skipif(
    not OPENAI_API_KEY,
    reason="OPENAI_API_KEY not set — skipping live integration test"
)


@requires_openai
def test_litellm_chat_completions():
    """LiteLLM /v1/chat/completions with gpt-4.1-mini returns a non-empty response."""
    response = httpx.post(
        f"{LITELLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
        json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "Say 'pong' and nothing else."}]},
        timeout=30,
    )
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    content = data["choices"][0]["message"]["content"]
    assert content and len(content) > 0


@requires_openai
def test_llm_router_heavy_stage_integration():
    """llm_router.route_request for a heavy stage returns non-stub content via LiteLLM."""
    import sys
    sys.path.insert(0, ".")
    from services.llm_router import route_request, HEAVY_STAGES

    assert "describe" in HEAVY_STAGES
    result = route_request("describe", "In one word, what is Python?")
    assert result.provider == "litellm"
    assert result.content not in ("", "[stub]")
