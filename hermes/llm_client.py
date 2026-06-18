"""Async LLM client for the Hermes agent, backed by freellmapi."""
import os

from openai import AsyncOpenAI

FREELLMAPI_BASE_URL: str = os.getenv("FREELLMAPI_BASE_URL", "http://freellmapi:3001/v1")
FREELLMAPI_API_KEY: str = os.getenv("FREELLMAPI_API_KEY", "")


class HermesLLMClient:
    """Typed async wrapper around openai.AsyncOpenAI pointed at freellmapi."""

    def __init__(
        self,
        base_url: str = FREELLMAPI_BASE_URL,
        api_key: str = FREELLMAPI_API_KEY,
    ) -> None:
        # AsyncOpenAI rejects empty-string api_key; freellmapi validates its own token
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "no-key")

    async def chat(
        self,
        messages: list[dict],
        model: str = "auto",
    ) -> str:
        """Send a chat completion request and return the response text."""
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
