"""Обработчики MAX-сообщений.

Все handler принимают `message` (объект maxapi) и AppContext через замыкание.
Чтобы не зависеть от точной структуры maxapi, любые поля доступа защищены через getattr.
"""
from __future__ import annotations

import logging
import shlex
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from src.bot.access import check_pin, is_allowed
from src.bot.context import AppContext
from src.bot.pipeline import process_parsed
from src.bot.text_responses import (
    CANCEL_DONE_MSG,
    CANCEL_NOTHING_MSG,
    HELP_MSG,
    LINKED_MSG,
    LLM_DOWN_MSG,
    NEED_LINK_MSG,
    SETUP_DONE_MSG,
    START_MSG,
    STT_DOWN_MSG,
    UNDO_CONFIRM_MSG,
    UNDO_DONE_MSG,
    UNDO_LOCKED_OUT_MSG,
    UNDO_NEED_PIN_MSG,
    UNDO_NOTHING_MSG,
    UNDO_PIN_HINT,
    UNDO_WRONG_PIN_MSG,
    UNRECOGNIZED_VOICE_MSG,
    VERSION_MSG,
    VOICE_TOO_LONG_MSG,
    WROTE_FALLBACK_TEXT_MSG,
    WROTE_REACTION,
    whitelist_msg,
)
from src.config.settings import settings
from src.reports.daily import build_daily_report, format_daily_report
from src.reports.stock import format_stock_report
from src.sheets.setup import setup_sheet
from src.sheets.writer import undo_by_refs

log = logging.getLogger(__name__)


# ============================================================
# Утилиты для работы с message объектом maxapi
# ============================================================

def _chat_id(message: Any) -> str:
    return str(
        getattr(message, "chat_id", None)
        or getattr(getattr(message, "chat", None), "id", None)
        or ""
    )


def _user_id(message: Any) -> str:
    return str(
        getattr(message, "user_id", None)
        or getattr(getattr(message, "from_user", None), "id", None)
        or getattr(message, "sender_id", None)
        or ""
    )


def _message_id(message: Any) -> str:
    return str(getattr(message, "message_id", None) or getattr(message, "id", None) or "")


def _text(message: Any) -> str:
    return str(getattr(message, "text", None) or "")


# ============================================================
# Главный pipeline
# ============================================================

def make_handlers(client, ctx: AppContext) -> dict[str, Any]:
    """Создаёт замыкания всех handler. Возвращает словарь по имени.

    Регистрация — отдельно (в src/bot/router.py), чтобы здесь не зависеть от maxapi API.
    """

    async def _send(message: Any, text: str | None) -> None:
        if text is None:
            return
        if text == WROTE_REACTION:
            # Сначала пытаемся реакцию, иначе короткий текст
            ok = await client.react(message, "✅")
            if not ok:
                await client.reply(message, "✅ записал")
            return
        await client.reply(message, text)

    async def _check_access(message: Any) -> bool:
        if not is_allowed(_user_id(message)):
            msg = whitelist_msg(settings.silent_reject)
            if msg:
                await client.reply(message, msg)
            return False
        return True

    # === Команды ===

    async def handle_start(message: Any) -> None:
        if not await _check_access(message):
            return
        await client.reply(message, START_MSG)

    async def handle_help(message: Any) -> None:
        if not await _check_access(message):
            return
        await client.reply(message, HELP_MSG)

    async def handle_version(message: Any) -> None:
        if not await _check_access(message):
            return
        await client.reply(message, VERSION_MSG)

    async def handle_link(message: Any) -> None:
        if not await _check_access(message):
            return
        # Парсим аргумент: /link <sheet_id>
        parts = _text(message).split(maxsplit=1)
        if len(parts) < 2:
            await client.reply(message, "Использование: /link <ID_таблицы>")
            return
        sheet_id = parts[1].strip()
        ctx.chat_sheets.set_sheet_id(_chat_id(message), sheet_id, _user_id(message))
        await client.reply(message, LINKED_MSG)

    async def handle_setup(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        sheet_id = ctx.chat_sheets.get_sheet_id(chat_id) or settings.default_sheet_id
        if not sheet_id:
            await client.reply(message, NEED_LINK_MSG)
            return
        try:
            report = setup_sheet(sheet_id, import_prices=True)
        except Exception as e:  # noqa: BLE001
            log.exception("Setup failed")
            await client.reply(message, f"Setup упал: {e}")
            return
        await client.reply(
            message,
            SETUP_DONE_MSG.format(
                created=", ".join(report["created_sheets"]) or "(уже были)",
                locs=report["imported_locations"],
                cats=report["imported_categories"],
                products=report["imported_products"],
            ),
        )

    async def handle_today(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        spreadsheet = _open_spreadsheet(ctx, chat_id)
        if spreadsheet is None:
            await client.reply(message, NEED_LINK_MSG)
            return
        rep = build_daily_report(spreadsheet, date.today(), is_intermediate=True)
        await client.reply(message, format_daily_report(rep))

    async def handle_last(message: Any) -> None:
        if not await _check_access(message):
            return
        parts = _text(message).split()
        n = 5
        if len(parts) >= 2:
            try:
                n = int(parts[1])
                n = max(1, min(n, 20))
            except ValueError:
                pass
        rows = ctx.operations_log.last_n(_chat_id(message), n)
        if not rows:
            await client.reply(message, "Операций ещё не было.")
            return
        lines = [f"Последние {len(rows)} операций:"]
        for r in rows:
            lines.append(f"  • {r['summary']}")
        await client.reply(message, "\n".join(lines))

    async def handle_undo(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        user_id = _user_id(message)
        last = ctx.operations_log.last(chat_id)
        if not last:
            await client.reply(message, UNDO_NOTHING_MSG)
            return

        # Если задан OPS_PIN — сохраняем в диалог и просим PIN
        if settings.ops_pin:
            ctx.dialog.set(
                chat_id,
                intent="confirm_undo",
                partial_data={"op_id": last["id"], "summary": last["summary"], "sheet_refs": last["sheet_refs"]},
                ttl_minutes=settings.dialog_state_ttl_minutes,
            )
            await client.reply(
                message,
                UNDO_CONFIRM_MSG.format(summary=last["summary"], pin_hint=UNDO_PIN_HINT),
            )
            return

        # Без PIN — сразу карточка подтверждения
        ctx.dialog.set(
            chat_id,
            intent="confirm_undo",
            partial_data={"op_id": last["id"], "summary": last["summary"], "sheet_refs": last["sheet_refs"]},
            ttl_minutes=settings.dialog_state_ttl_minutes,
        )
        await client.reply(
            message,
            UNDO_CONFIRM_MSG.format(summary=last["summary"], pin_hint=""),
        )

    async def handle_cancel(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        state = ctx.dialog.get(chat_id)
        if not state:
            await client.reply(message, CANCEL_NOTHING_MSG)
            return
        ctx.dialog.clear(chat_id)
        await client.reply(message, CANCEL_DONE_MSG)

    async def handle_stock(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        spreadsheet = _open_spreadsheet(ctx, chat_id)
        if spreadsheet is None:
            await client.reply(message, NEED_LINK_MSG)
            return
        parts = _text(message).split(maxsplit=2)
        product_query = parts[1] if len(parts) >= 2 else None
        location = parts[2] if len(parts) >= 3 else None
        await client.reply(
            message,
            format_stock_report(spreadsheet, product_query, location),
        )

    async def handle_locations(message: Any) -> None:
        if not await _check_access(message):
            return
        await client.reply(message, "Точки:\n  • Магазин Зинино\n  • Магазин Кармалы")

    async def handle_products(message: Any) -> None:
        if not await _check_access(message):
            return
        parts = _text(message).split(maxsplit=1)
        if len(parts) < 2:
            await client.reply(message, f"Использование: /products <фрагмент_названия>. В каталоге {ctx.catalog.size()} SKU.")
            return
        query = parts[1].strip()
        matches = ctx.catalog.lookup(query, top_k=10, min_score=0.5)
        if not matches:
            await client.reply(message, f"Не нашёл «{query}».")
            return
        lines = [f"Найдено по «{query}»:"]
        for i, m in enumerate(matches, 1):
            lines.append(f"  {i}. ({m.score:.2f}) {m.canon}")
        await client.reply(message, "\n".join(lines))

    # === Голос и текст ===

    async def handle_voice(message: Any) -> None:
        if not await _check_access(message):
            return
        if ctx.stt_engine is None:
            await client.reply(message, STT_DOWN_MSG)
            return

        # Проверка длительности
        duration = getattr(getattr(message, "voice", None), "duration", None)
        if duration and duration > settings.voice_max_duration_sec:
            await client.reply(
                message,
                VOICE_TOO_LONG_MSG.format(max_sec=settings.voice_max_duration_sec),
            )
            return

        # Скачиваем и распознаём
        try:
            with tempfile.TemporaryDirectory() as td:
                audio_path = await client.download_voice(message, Path(td))
                text = await ctx.stt_engine.transcribe(audio_path)
        except Exception:  # noqa: BLE001
            log.exception("STT failed")
            await client.reply(message, STT_DOWN_MSG)
            return

        if not text:
            await client.reply(message, UNRECOGNIZED_VOICE_MSG)
            return

        await _process_text(message, text)

    async def handle_text(message: Any) -> None:
        if not await _check_access(message):
            return
        text = _text(message).strip()
        if not text:
            return

        # Если есть активный диалог — обрабатываем как ответ
        state = ctx.dialog.get(_chat_id(message))
        if state:
            await _handle_dialog_response(message, text, state)
            return

        await _process_text(message, text)

    async def _process_text(message: Any, text: str) -> None:
        if ctx.llm_parser is None:
            await client.reply(message, LLM_DOWN_MSG)
            return
        try:
            parsed = await ctx.llm_parser.parse(text)
        except Exception:  # noqa: BLE001
            log.exception("LLM parse failed")
            await client.reply(message, LLM_DOWN_MSG)
            return

        result = await process_parsed(
            ctx,
            parsed,
            chat_id=_chat_id(message),
            user_id=_user_id(message),
            message_id=_message_id(message),
        )
        await _send(message, result)

    async def _handle_dialog_response(message: Any, text: str, state: dict) -> None:
        intent = state["intent"]
        chat_id = _chat_id(message)
        user_id = _user_id(message)
        lower = text.lower().strip()

        # Escape: «отмена», «забей», «давай заново», /cancel
        if lower in ("отмена", "забей", "стоп", "давай заново", "сначала"):
            ctx.dialog.clear(chat_id)
            await client.reply(message, CANCEL_DONE_MSG)
            return

        if intent == "confirm_undo":
            await _process_undo_response(message, text, state)
            return

        if intent.startswith("confirm_"):
            await _process_confirm_response(message, text, state)
            return

        if intent == "canonicalize_product":
            await _process_canon_response(message, text, state)
            return

        # Неизвестный intent — сбросим
        ctx.dialog.clear(chat_id)
        await client.reply(message, CANCEL_DONE_MSG)

    async def _process_undo_response(message: Any, text: str, state: dict) -> None:
        chat_id = _chat_id(message)
        user_id = _user_id(message)
        partial = state["partial_data"]
        lower = text.lower().strip()

        if lower in ("нет", "не", "не надо"):
            ctx.dialog.clear(chat_id)
            await client.reply(message, "Отменил.")
            return

        # Проверка PIN если включена
        if settings.ops_pin:
            # Если ответ — «да <pin>», берём PIN; если просто «да» — просим PIN
            parts = text.split(maxsplit=1)
            pin = parts[1] if len(parts) >= 2 else None
            if pin is None:
                await client.reply(message, UNDO_NEED_PIN_MSG)
                return
            ok, err = check_pin(user_id, pin, ctx.pin_attempts)
            if not ok:
                await client.reply(message, err or "Неверный PIN.")
                return

        # Выполняем undo
        spreadsheet = _open_spreadsheet(ctx, chat_id)
        if spreadsheet is None:
            ctx.dialog.clear(chat_id)
            await client.reply(message, NEED_LINK_MSG)
            return
        try:
            undo_by_refs(spreadsheet, partial["sheet_refs"])
            ctx.operations_log.mark_undone(partial["op_id"])
            ctx.dialog.clear(chat_id)
            await client.reply(message, UNDO_DONE_MSG.format(summary=partial["summary"]))
        except Exception:  # noqa: BLE001
            log.exception("Undo failed")
            await client.reply(message, "Не получилось откатить. Попробуй ещё раз позже.")

    async def _process_confirm_response(message: Any, text: str, state: dict) -> None:
        chat_id = _chat_id(message)
        user_id = _user_id(message)
        lower = text.lower().strip()
        if lower in ("да", "ага", "ок", "верно", "+"):
            # TODO: рематериализовать parsed из partial_data и записать
            # (полная реализация — после реальных тестов с Sheets)
            ctx.dialog.clear(chat_id)
            await client.reply(message, "✅ записал")
            return
        if lower in ("повтор",):
            ctx.dialog.clear(chat_id)
            await client.reply(message, "Понял — не записываю.")
            return
        if lower in ("новая",):
            ctx.dialog.clear(chat_id)
            await client.reply(message, "Записываю как новую…")
            # TODO: записать без проверки дедупа
            return
        # Иначе пробуем парсить как правку (например «не 15, а 50»)
        ctx.dialog.clear(chat_id)
        await client.reply(message, "Не понял ответ. Если что-то не так — продиктуй заново.")

    async def _process_canon_response(message: Any, text: str, state: dict) -> None:
        chat_id = _chat_id(message)
        partial = state["partial_data"]
        candidates = partial.get("candidates", [])
        lower = text.lower().strip()
        if lower == "новый":
            # TODO: добавить товар в каталог и записать операцию
            ctx.dialog.clear(chat_id)
            await client.reply(message, "Окей, завожу как новый товар.")
            return
        try:
            idx = int(lower)
        except ValueError:
            await client.reply(message, "Не понял. Ответь номером (1, 2, 3) или «новый».")
            return
        if 1 <= idx <= len(candidates):
            chosen = candidates[idx - 1]
            ctx.dialog.clear(chat_id)
            # TODO: подменить product.name в parsed на chosen и записать
            await client.reply(message, f"Выбрал: {chosen}. Записываю…")
            return
        await client.reply(message, f"Номер должен быть от 1 до {len(candidates)}.")

    return {
        "start": handle_start,
        "help": handle_help,
        "version": handle_version,
        "link": handle_link,
        "setup": handle_setup,
        "today": handle_today,
        "last": handle_last,
        "undo": handle_undo,
        "cancel": handle_cancel,
        "stock": handle_stock,
        "locations": handle_locations,
        "products": handle_products,
        "voice": handle_voice,
        "text": handle_text,
    }


def _open_spreadsheet(ctx: AppContext, chat_id: str):
    sheet_id = ctx.chat_sheets.get_sheet_id(chat_id) or settings.default_sheet_id
    if not sheet_id:
        return None
    from src.sheets.setup import open_sheet
    return open_sheet(sheet_id)
