"""LLM router: routes heavy stages directly to opencode.ai Zen API.

Heavy stages (describe, architecture, codegen, testgen, classify, autofix)
call opencode.ai/zen/v1 (OpenAI-compatible) with deepseek-v4-flash-free.
Light stages return a stub response.

Threat mitigations applied:
- T-02-05: Stage checked against HEAVY_STAGES before any LLM call.
- T-03-05: Prompt content validated at webhook layer (max_length).
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

HEAVY_STAGES = {"describe", "architecture", "codegen", "testgen", "classify", "autofix"}

_OPENCODE_BASE_URL = "https://opencode.ai/zen/v1"
_DEFAULT_MODEL = "deepseek-v4-flash-free"


@dataclass
class LLMResponse:
    provider: str
    content: str
    model: str = ""
    reasoning: str = ""


def route_request(stage: str, prompt: str) -> LLMResponse:
    """Route a prompt to opencode.ai for heavy stages, stub for light."""
    if stage not in HEAVY_STAGES:
        main_model = os.environ.get("MAIN_MODEL", "claude-3-5-haiku-20241022")
        logger.info("Routing %s to main model %s (stub)", stage, main_model)
        return LLMResponse(provider="main_model", content="[stub]", model=main_model)

    api_key = os.environ.get("OPENCODE_API_KEY", "")
    model = os.environ.get("OPENCODE_MODEL", _DEFAULT_MODEL)
    logger.info("Routing %s to opencode.ai/%s", stage, model)

    try:
        resp = httpx.post(
            f"{_OPENCODE_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        return LLMResponse(
            provider="opencode",
            content=message["content"],
            model=data.get("model", model),
            reasoning=reasoning,
        )
    except Exception as exc:
        logger.warning("opencode.ai call failed for stage %s: %s — returning stub", stage, exc)
        return LLMResponse(provider="opencode", content="[stub]", model=model)
