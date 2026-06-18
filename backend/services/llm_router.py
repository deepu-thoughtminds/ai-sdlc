"""LLM router: routes requests to freellmapi (heavy) or main model (light).

Heavy stages (describe, architecture, codegen, testgen) are sent to the
freellmapi service via the Ollama native /api/chat endpoint. Light stages
(assign) use the configured main model — in the Walking Skeleton, the light
path returns a stub response without making a real API call.

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
HEAVY_STAGES = {"describe", "architecture", "codegen", "testgen"}


@dataclass
class LLMResponse:
    """Response from an LLM routing call."""

    provider: str  # "freellmapi" or "main_model"
    content: str  # response text
    model: str = ""  # model name used


def route_request(stage: str, prompt: str) -> LLMResponse:
    """Route a prompt to the appropriate LLM provider based on stage.

    Heavy stages → freellmapi via Ollama native /api/chat endpoint.
    Light stages → main model stub (no real API call in Walking Skeleton).

    Ollama /api/chat request format:
      POST {FREELLMAPI_BASE_URL}/api/chat
      {"model": "<model>", "messages": [{"role": "user", "content": "<prompt>"}], "stream": false}

    Ollama /api/chat response format:
      {"model": "<model>", "message": {"role": "assistant", "content": "<text>"}, ...}

    Args:
        stage: The pipeline stage name (must have been validated by parse_mention).
        prompt: The full prompt text to send to the model.

    Returns:
        LLMResponse with provider, content, and model fields.
    """
    freellmapi_base_url = os.environ.get("FREELLMAPI_BASE_URL", "http://freellmapi:11434")
    freellmapi_model = os.environ.get("FREELLMAPI_MODEL", "llama3")
    main_model = os.environ.get("MAIN_MODEL", "claude-3-5-haiku-20241022")

    if stage in HEAVY_STAGES:
        logger.info("Routing %s to freellmapi at %s", stage, freellmapi_base_url)
        payload = {
            "model": freellmapi_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            resp = httpx.post(
                f"{freellmapi_base_url}/api/chat",
                json=payload,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama native format: data["message"]["content"]
            response_text = data["message"]["content"]
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
