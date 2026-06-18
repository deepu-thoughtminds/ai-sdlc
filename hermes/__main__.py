"""Entry point for `python -m hermes`."""
import asyncio
import logging
import os

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("hermes")


async def main() -> None:
    logger.info("Hermes agent started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
