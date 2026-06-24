"""LLM router: routes requests to freellmapi (heavy) or main model (light).

Heavy stages (describe, architecture, codegen, testgen) are sent to the
freellmapi service via the OpenAI-compatible /v1/chat/completions endpoint
with Bearer auth. Light stages (assign) use the configured main model —
in the Walking Skeleton, the light path returns a stub response without
making a real API call.

Threat mitigations applied:
- T-02-05: Stage is checked against HEAVY_STAGES; routing only happens for
  stages already validated by parse_mention's KNOWN_STAGES guard.
- T-02-03: freellmapi is an internal service on ai-sdlc-net; prompts do not
  leave the Docker network.
- T-03-05: Prompt content comes from Jira comment body (validated max_length
  at webhook layer); freellmapi is internal-only; no tool-calling surface.
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# "describe" added in phase 03-01 — routes to freellmapi/Ollama for
# codebase-aware description elaboration.
# "classify" added in Phase 10 — routes complexity classification to freellmapi
# for deterministic JSON-structured LLM judgment (CLASSIFY-01, CLASSIFY-02).
HEAVY_STAGES = {"describe", "architecture", "codegen", "testgen", "classify", "autofix"}


@dataclass
class LLMResponse:
    """Response from an LLM routing call."""

    provider: str  # "freellmapi" or "main_model"
    content: str  # response text
    model: str = ""  # model name used


FREELLMAPI_API_KEY = os.getenv("FREELLMAPI_API_KEY", "")
FREELLMAPI_MODELS = os.getenv("FREELLMAPI_MODELS", "auto")


def route_request(stage: str, prompt: str) -> LLMResponse:
    """Route a prompt to the appropriate LLM provider based on stage.

    Heavy stages → freellmapi via OpenAI-compatible /v1/chat/completions endpoint.
    Light stages → main model stub (no real API call in Walking Skeleton).

    OpenAI /v1/chat/completions request format:
      POST {FREELLMAPI_BASE_URL}/v1/chat/completions
      Authorization: Bearer {FREELLMAPI_API_KEY}
      {"model": "auto", "messages": [{"role": "user", "content": "<prompt>"}]}

    OpenAI /v1/chat/completions response format:
      {"choices": [{"message": {"role": "assistant", "content": "<text>"}}], ...}

    Args:
        stage: The pipeline stage name (must have been validated by parse_mention).
        prompt: The full prompt text to send to the model.

    Returns:
        LLMResponse with provider, content, and model fields.
    """
    freellmapi_base_url = os.environ.get("FREELLMAPI_BASE_URL", "http://freellmapi:3001/v1")
    freellmapi_api_key = os.environ.get("FREELLMAPI_API_KEY", FREELLMAPI_API_KEY)
    freellmapi_model = os.environ.get("FREELLMAPI_MODELS", FREELLMAPI_MODELS)
    main_model = os.environ.get("MAIN_MODEL", "claude-3-5-haiku-20241022")

    if stage in HEAVY_STAGES:
        logger.info("Routing %s to freellmapi at %s", stage, freellmapi_base_url)
        payload = {
            "model": freellmapi_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = httpx.post(
                f"{freellmapi_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {freellmapi_api_key}"},
                json=payload,
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # OpenAI format: data["choices"][0]["message"]["content"]
            response_text = data["choices"][0]["message"]["content"]
            model_name = data.get("model", freellmapi_model)
            return LLMResponse(provider="freellmapi", content=response_text, model=model_name)
        except Exception as exc:
            logger.warning(
                "freellmapi call failed for stage %s: %s — returning stub response",
                stage,
                exc,
            )
            return LLMResponse(provider="freellmapi", content="[stub]", model=freellmapi_model)

    # Light stage — stub response in Walking Skeleton
    logger.info("Routing %s to main model %s", stage, main_model)
    return LLMResponse(provider="main_model", content="[stub]", model=main_model)
