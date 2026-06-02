"""Точка входа max-money-bot.

Запуск:
    python -m src.main

Перед запуском нужно заполнить .env (минимум: MAX_BOT_TOKEN, GIGACHAT_CREDENTIALS,
GOOGLE_SERVICE_ACCOUNT_JSON, ALLOWED_USER_IDS).
"""
from __future__ import annotations

import asyncio
import logging

from src.bot.context import AppContext
from src.bot.max_client import MAXClient
from src.bot.router import register_all
from src.config.settings import settings
from src.scheduler.daily_job import start_scheduler, stop_scheduler


def setup_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )


async def main() -> None:
    setup_logging()
    log = logging.getLogger("main")
    log.info("max-money-bot starting (v2.1, российский стек)")

    # 1. Контекст: SQLite, кеши, парсер, STT
    ctx = AppContext.bootstrap(with_llm=True, with_stt=True)

    # 2. MAX-клиент
    client = MAXClient()

    # 3. Регистрация хендлеров
    register_all(client, ctx)

    # 4. Планировщик (дневной отчёт + GC + ретраи)
    start_scheduler(ctx, client)

    try:
        # 5. Long-polling
        await client.start_polling()
    except KeyboardInterrupt:
        log.info("Получен SIGINT, останавливаюсь")
    finally:
        stop_scheduler()
        ctx.db.close()
        log.info("Bye")


if __name__ == "__main__":
    asyncio.run(main())
