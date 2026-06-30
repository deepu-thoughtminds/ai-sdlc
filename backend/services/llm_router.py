"""LLM router: routes all heavy stages to LiteLLM/gpt-4.1-mini.

Heavy stages (describe, architecture, codegen, testgen, classify, autofix)
are sent via the LiteLLM proxy OpenAI-compatible endpoint. Light stages
return a stub response.

Threat mitigations applied:
- T-02-05: Stage is checked against HEAVY_STAGES; routing only happens for
  stages already validated by parse_mention's KNOWN_STAGES guard.
- T-02-03: LiteLLM proxy is an internal service on ai-sdlc-net.
- T-03-05: Prompt content comes from Jira comment body (validated max_length
  at webhook layer).
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

HEAVY_STAGES = {"describe", "architecture", "codegen", "testgen", "classify", "autofix"}


@dataclass
class LLMResponse:
    """Response from an LLM routing call."""

    provider: str
    content: str
    model: str = ""
    reasoning: str = ""


def route_request(stage: str, prompt: str) -> LLMResponse:
    """Route a prompt to gpt-4.1-mini via LiteLLM for heavy stages, stub for light."""
    if stage not in HEAVY_STAGES:
        main_model = os.environ.get("MAIN_MODEL", "claude-3-5-haiku-20241022")
        logger.info("Routing %s to main model %s", stage, main_model)
        return LLMResponse(provider="main_model", content="[stub]", model=main_model)

    base_url = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000/v1")
    api_key = os.environ.get("LITELLM_MASTER_KEY", "sk-litellm-local")
    model = "gpt-4.1-mini"
    logger.info("Routing %s to LiteLLM/gpt-4.1-mini at %s", stage, base_url)

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
        native_reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        return LLMResponse(
            provider="litellm",
            content=message["content"],
            model=data.get("model", model),
            reasoning=native_reasoning,
        )
    except Exception as exc:
        logger.warning("LiteLLM call failed for stage %s: %s — returning stub", stage, exc)
        return LLMResponse(provider="litellm", content="[stub]", model=model)
