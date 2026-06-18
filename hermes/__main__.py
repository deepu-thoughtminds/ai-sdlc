"""Entry point for `python -m hermes`."""
import asyncio
import logging
import os

import uvicorn

from hermes.llm_client import HermesLLMClient

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("hermes")


async def _llm_self_test(client: HermesLLMClient) -> None:
    """Ping freellmapi at startup. Logs result; never raises."""
    try:
        result = await client.chat(
            [{"role": "user", "content": "Reply with the single word: pong"}],
            model="auto",
        )
        logger.info("LLM self-test passed: %s", result[:80])
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM self-test failed: %s", exc)


def main() -> None:
    """Start Hermes: run LLM self-test then start the FastAPI server."""
    logger.info("Hermes agent started")
    client = HermesLLMClient()
    asyncio.run(_llm_self_test(client))
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    uvicorn.run("hermes.server:app", host="0.0.0.0", port=8001, log_level=log_level)


if __name__ == "__main__":
    main()
