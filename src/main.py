"""Точка входа. Long-polling MAX Bot API."""
import asyncio
import logging

from src.config.settings import settings


async def main() -> None:
    logging.basicConfig(level=settings.log_level)
    log = logging.getLogger(__name__)
    log.info("max-money-bot starting (skeleton)")
    # TODO: инициализировать MAX client, sheets client, llm parser, stt
    # TODO: запустить long-polling loop
    raise NotImplementedError("MAX Bot API client ещё не реализован")


if __name__ == "__main__":
    asyncio.run(main())
