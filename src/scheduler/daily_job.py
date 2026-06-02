"""APScheduler: дневной автоотчёт + фоновые таски GC и ретрая pending_writes.

Запускается из src/main.py после bootstrap AppContext.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from src.config.settings import settings

if TYPE_CHECKING:
    from src.bot.context import AppContext
    from src.bot.max_client import MAXClient

log = logging.getLogger(__name__)
_scheduler = None


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


async def daily_report_job(ctx: "AppContext", client: "MAXClient") -> None:
    """Сформировать и разослать дневной отчёт во все известные чаты."""
    from src.reports.daily import build_daily_report, format_daily_report
    from src.sheets.setup import open_sheet

    # Берём все привязанные чаты
    rows = ctx.db.execute("SELECT chat_id, sheet_id FROM chat_sheets").fetchall()
    if not rows:
        log.info("daily_report_job: ни одного chat не привязано — пропуск")
        return

    today = date.today()
    for row in rows:
        chat_id, sheet_id = row["chat_id"], row["sheet_id"]
        attempts = 0
        while attempts < settings.daily_report_max_retries:
            try:
                spreadsheet = open_sheet(sheet_id)
                rep = build_daily_report(spreadsheet, today, is_intermediate=False)
                text = format_daily_report(rep)
                await client.send_message(chat_id, text)
                log.info("daily_report_job: отправлен в chat=%s", chat_id)
                break
            except Exception:  # noqa: BLE001
                attempts += 1
                log.exception(
                    "daily_report_job: попытка %d/%d упала для chat=%s",
                    attempts,
                    settings.daily_report_max_retries,
                    chat_id,
                )
        else:
            # Все попытки исчерпаны
            ctx.db.execute(
                "INSERT OR REPLACE INTO missed_reports "
                "(report_date, chat_id, attempts, last_attempt_at, last_error) "
                "VALUES (?, ?, ?, datetime('now'), 'all_retries_exhausted')",
                (today.isoformat(), chat_id, attempts),
            )


async def gc_job(ctx: "AppContext") -> None:
    """Чистка устаревших dedup_window и dialog_state. Запускается каждую минуту."""
    n_dedup = ctx.dedup.gc_expired()
    n_dialog = ctx.dialog.gc_expired()
    if n_dedup or n_dialog:
        log.debug("gc: dedup=%d, dialog=%d", n_dedup, n_dialog)


async def pending_writes_retry_job(ctx: "AppContext", client: "MAXClient") -> None:
    """Ретрай отложенных записей в Sheets. Запускается каждую минуту.

    Стратегия: рематериализуем pydantic-операцию из payload, заново вызываем
    write_rehydrated. При успехе — удаляем из очереди и уведомляем клиента.
    При повторной ошибке — увеличиваем счётчик попыток (мягкий exp-backoff
    через ограничение max_attempts).
    """
    from src.bot.pipeline import rehydrate_parsed, write_rehydrated
    from src.bot.text_responses import WROTE_REACTION

    pending = ctx.pending_writes.list_ready(max_attempts=10)
    if not pending:
        return
    log.info("pending_writes_retry: %d ожидающих", len(pending))

    for row in pending:
        pid = row["id"]
        chat_id = row["chat_id"]
        payload = row["payload"]
        try:
            parsed = rehydrate_parsed(payload["parsed_class"], payload["parsed_json"])
        except Exception as e:  # noqa: BLE001
            log.exception("pending_writes_retry: rehydrate failed для pid=%s", pid)
            ctx.pending_writes.mark_attempt(pid, f"rehydrate: {e}")
            continue

        try:
            result = await write_rehydrated(
                ctx,
                parsed,
                chat_id=chat_id,
                user_id=row.get("user_id") or "system",
                message_id=f"retry_{pid}",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("pending_writes_retry: write failed для pid=%s", pid)
            ctx.pending_writes.mark_attempt(pid, str(e)[:500])
            continue

        ctx.pending_writes.delete(pid)
        log.info("pending_writes_retry: pid=%s записан", pid)
        # Уведомить клиента — короткий текст, без реакции на retry
        try:
            note = "✅ записал отложенную операцию" if result == WROTE_REACTION else result
            await client.send_message(chat_id, note)
        except Exception:  # noqa: BLE001
            log.exception("pending_writes_retry: уведомить чат не удалось pid=%s", pid)


def start_scheduler(ctx: "AppContext", client: "MAXClient | None"):
    """Запуск всех периодических задач."""
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore
    except ImportError:
        log.warning("apscheduler не установлен — расписание не работает")
        return None

    sched = AsyncIOScheduler(timezone=settings.tz)

    # Дневной автоотчёт по cron
    hour, minute = _parse_hhmm(settings.daily_report_time)
    if client is not None:
        sched.add_job(
            daily_report_job,
            CronTrigger(hour=hour, minute=minute, timezone=settings.tz),
            args=[ctx, client],
            id="daily_report",
            replace_existing=True,
        )

    # GC каждую минуту
    sched.add_job(
        gc_job,
        IntervalTrigger(minutes=1),
        args=[ctx],
        id="gc",
        replace_existing=True,
    )

    # Ретрай pending_writes каждую минуту
    if client is not None:
        sched.add_job(
            pending_writes_retry_job,
            IntervalTrigger(minutes=1),
            args=[ctx, client],
            id="pending_writes_retry",
            replace_existing=True,
        )

    sched.start()
    _scheduler = sched
    log.info("Scheduler started: daily=%s, GC=1m, retries=1m", settings.daily_report_time)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
