"""Entry point for `python -m hermes`."""
import asyncio
import logging
import os

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


async def main() -> None:
    logger.info("Hermes agent started")
    client = HermesLLMClient()
    await _llm_self_test(client)
    try:
        await asyncio.Event().wait()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
