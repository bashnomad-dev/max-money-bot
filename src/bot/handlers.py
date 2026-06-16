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
from src.bot.pipeline import process_parsed, rehydrate_parsed, write_rehydrated
from src.bot.text_responses import (
    CANCEL_DONE_MSG,
    CANCEL_NOTHING_MSG,
    HELP_MSG,
    LINKED_MSG,
    LLM_DOWN_MSG,
    NEED_LINK_MSG,
    REPAIR_DONE_MSG,
    REPAIR_FAILED_MSG,
    REPAIR_START_MSG,
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
from src.canonicalize import canonicalize_location
from src.config.settings import settings
from src.reports.daily import build_daily_report, format_daily_report
from src.reports.stock import format_stock_report
from src.sheets.setup import setup_sheet
from src.sheets.writer import edit_last_field, undo_by_refs
from src.stock.sheets_sync import repair_full

log = logging.getLogger(__name__)


# ============================================================
# Утилиты для работы с message объектом maxapi
# ============================================================

def _chat_id(message: Any) -> str:
    """maxapi.Message: recipient.chat_id (групповой) либо recipient.user_id (личка)."""
    rec = getattr(message, "recipient", None)
    cid = getattr(rec, "chat_id", None)
    if cid is None:
        cid = getattr(rec, "user_id", None)
    if cid is None:
        cid = getattr(message, "chat_id", None)
    return str(cid or "")


def _user_id(message: Any) -> str:
    """Отправитель: maxapi.Message.sender.user_id."""
    snd = getattr(message, "sender", None)
    uid = getattr(snd, "user_id", None) or getattr(message, "user_id", None)
    return str(uid or "")


def _message_id(message: Any) -> str:
    """maxapi.Message.body.mid (строковый id)."""
    body = getattr(message, "body", None)
    mid = getattr(body, "mid", None) or getattr(message, "message_id", None)
    return str(mid or "")


def _text(message: Any) -> str:
    body = getattr(message, "body", None)
    return str(getattr(body, "text", None) or getattr(message, "text", None) or "")


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
        user_id = _user_id(message)
        if not is_allowed(user_id):
            log.info("access denied: user_id=%s не в whitelist", user_id)
            msg = whitelist_msg(settings.silent_reject)
            if msg:
                await client.reply(message, msg)
            return False
        log.info("access granted: user_id=%s", user_id)
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

    async def handle_edit(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        rest = _text(message).split()[1:]  # без самой команды
        # Необязательное «last»/«последнюю» — правим всегда последнюю операцию.
        if rest and rest[0].lower() in ("last", "последнюю", "последняя", "последнее"):
            rest = rest[1:]
        if len(rest) < 2:
            await client.reply(
                message,
                "Использование: /правка [последнюю] <поле> <значение>\n"
                "Поля: сумма, контрагент, описание.\n"
                "Например: /правка сумма 18000",
            )
            return
        field, value = rest[0], " ".join(rest[1:])
        last = ctx.operations_log.last(chat_id)
        if not last:
            await client.reply(message, "Нечего править — операций ещё не было.")
            return
        spreadsheet = _open_spreadsheet(ctx, chat_id)
        if spreadsheet is None:
            await client.reply(message, NEED_LINK_MSG)
            return
        try:
            changed = edit_last_field(spreadsheet, last["sheet_refs"], field, value)
        except ValueError as e:
            await client.reply(message, str(e))
            return
        except Exception:  # noqa: BLE001
            log.exception("edit_last_field failed")
            await client.reply(message, "Не получилось изменить. Попробуй ещё раз позже.")
            return
        await client.reply(message, f"Поправил последнюю операцию — {changed}")

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

    async def handle_repair(message: Any) -> None:
        if not await _check_access(message):
            return
        chat_id = _chat_id(message)
        spreadsheet = _open_spreadsheet(ctx, chat_id)
        if spreadsheet is None:
            await client.reply(message, NEED_LINK_MSG)
            return
        await client.reply(message, REPAIR_START_MSG)
        try:
            rows, written = repair_full(spreadsheet)
        except Exception as e:  # noqa: BLE001
            log.exception("repair_full failed")
            await client.reply(message, REPAIR_FAILED_MSG.format(error=e))
            return
        await client.reply(message, REPAIR_DONE_MSG.format(rows=rows, written=written))

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

        if intent == "awaiting_supplement":
            await _process_supplement_response(message, text, state)
            return

        if intent == "awaiting_clarification":
            # Склеиваем оригинальный текст + новый ответ → парсим заново.
            # Это даёт LLM полный контекст (например: «Купил у Леруа 50 мешков
            # цемента» + «30000» → парсится как Purchase с amount=30000).
            original = state["partial_data"].get("original_text", "")
            combined = f"{original}. {text}".strip()
            ctx.dialog.clear(chat_id)
            await _process_text(message, combined)
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
        partial = state["partial_data"]
        lower = text.lower().strip()

        async def _do_write_from_state() -> None:
            try:
                parsed = rehydrate_parsed(partial["parsed_class"], partial["parsed_json"])
            except Exception:
                log.exception("rehydrate failed")
                ctx.dialog.clear(chat_id)
                await client.reply(message, "Не получилось восстановить операцию. Продиктуй заново.")
                return
            ctx.dialog.clear(chat_id)
            result = await write_rehydrated(
                ctx, parsed, chat_id=chat_id, user_id=user_id, message_id=_message_id(message),
            )
            await _send(message, result)

        # Нормализуем: убираем хвостовую пунктуацию/пробелы («да.», «да!» → «да»)
        answer = lower.strip(" .!,)(-")
        if answer in (
            "да", "ага", "ок", "окей", "верно", "+", "новая", "угу", "конечно",
            "да-да", "дада", "ну да", "запиши", "записывай", "сохрани", "сохраняй", "пиши",
        ):
            await _do_write_from_state()
            return
        if answer in ("нет", "не", "не надо", "повтор", "не записывай", "отмена"):
            ctx.dialog.clear(chat_id)
            await client.reply(message, "Понял — не записываю.")
            return
        ctx.dialog.clear(chat_id)
        await client.reply(message, "Не понял ответ. Если что-то не так — продиктуй заново.")

    async def _process_canon_response(message: Any, text: str, state: dict) -> None:
        chat_id = _chat_id(message)
        user_id = _user_id(message)
        partial = state["partial_data"]
        candidates = partial.get("candidates", [])
        raw = text.strip()
        lower = raw.lower()

        async def _write_with_canon(canon_name: str | None, is_existing: bool) -> None:
            """canon_name=None → пишем под сырым именем (line.name) как новый товар.
            canon_name + is_existing=True → подменяем на существующий канон из каталога.
            canon_name + is_existing=False → пользователь дал ПОЛНОЕ имя нового товара.

            После подмены — полный pipeline (process_parsed), сработают оставшиеся
            UX-проверки (карточка большой суммы, дедуп, confidence).
            Новые товары добавляются в каталог (in-memory + Sheets «Товары»),
            чтобы при следующей операции не было канонизации заново и не плодились
            дубликаты в Остатках.
            """
            try:
                parsed = rehydrate_parsed(partial["parsed_class"], partial["parsed_json"])
            except Exception:
                log.exception("rehydrate failed")
                ctx.dialog.clear(chat_id)
                await client.reply(message, "Не получилось восстановить операцию. Продиктуй заново.")
                return

            new_canons_to_persist: list[tuple[str, str]] = []  # (canon, unit)
            if hasattr(parsed, "lines"):
                for line in parsed.lines:
                    matches = ctx.catalog.lookup(line.name, top_k=1, min_score=0.99)
                    if matches:
                        continue
                    if canon_name:
                        line.name = canon_name
                    # помечаем как известный in-memory
                    ctx.dialog_engine.add_known_product(line.name)
                    # для новых товаров — добавить в каталог и persist
                    if not is_existing:
                        added = ctx.catalog.add(line.name, default_unit=line.unit)
                        if added:
                            new_canons_to_persist.append((line.name, line.unit))

            # persist в Sheets «Товары» (best-effort, не блокируем запись операции)
            if new_canons_to_persist:
                try:
                    from src.sheets.setup import append_product_to_sheet
                    ss = _open_spreadsheet(ctx, chat_id)
                    if ss is not None:
                        for canon, unit in new_canons_to_persist:
                            append_product_to_sheet(ss, canon, unit)
                except Exception:
                    log.exception("Не получилось persist новый товар в Sheets «Товары»")

            ctx.dialog.clear(chat_id)
            result = await process_parsed(
                ctx, parsed, chat_id=chat_id, user_id=user_id, message_id=_message_id(message),
            )
            await _send(message, result)

        # 1. «новый» — товар как есть (сырое имя из распознанной фразы)
        if lower == "новый":
            await _write_with_canon(None, is_existing=False)
            return

        # 2. Число — выбор из кандидатов («2», «2.», «2)» тоже считаем номером)
        num = raw.strip(" .)(-")
        if num.isdigit():
            idx = int(num)
            if 1 <= idx <= len(candidates):
                await _write_with_canon(candidates[idx - 1], is_existing=True)
                return
            await client.reply(message, f"Номер должен быть от 1 до {len(candidates)}.")
            return

        # 3. Текст ≥3 символов — полное имя нового товара
        if len(raw) >= 3:
            await _write_with_canon(raw, is_existing=False)
            return

        await client.reply(
            message,
            "Не понял. Ответь номером (1, 2, 3), «новый» или напиши полное имя нового товара.",
        )

    async def _process_supplement_response(message: Any, text: str, state: dict) -> None:
        """Короткое сообщение сразу после записи дополняет последнюю операцию
        (оплата / точка / контрагент / сумма). Если это новая операция — отдаём
        в обычный разбор, не проглатывая."""
        chat_id = _chat_id(message)
        partial = state["partial_data"]
        refs = partial.get("sheet_refs", [])
        raw = text.strip()
        low = raw.lower()

        field: str | None = None
        value = raw
        for pref, fld in (
            ("оплата", "оплата"), ("способ", "оплата"), ("точка", "точка"),
            ("контрагент", "контрагент"), ("клиент", "контрагент"),
            ("поставщик", "контрагент"), ("сумма", "сумма"),
        ):
            if low.startswith(pref):
                field = fld
                value = raw[len(pref):].strip(" :-—") or raw
                break

        if field is None and len(raw.split()) <= 2:
            # Голое короткое сообщение: «нал» / «Кармалы»
            pay_hints = ("нал", "карт", "счет", "счёт", "перевод", "безнал", "кэш", "расчет")
            if any(h in low for h in pay_hints):
                field, value = "оплата", raw
            elif canonicalize_location(raw) is not None:
                field, value = "точка", raw

        if field is None:
            # Не дополнение — это новая операция, отдаём в обычный разбор.
            ctx.dialog.clear(chat_id)
            await _process_text(message, text)
            return

        spreadsheet = _open_spreadsheet(ctx, chat_id)
        if spreadsheet is None:
            ctx.dialog.clear(chat_id)
            await client.reply(message, NEED_LINK_MSG)
            return
        ctx.dialog.clear(chat_id)
        try:
            changed = edit_last_field(spreadsheet, refs, field, value)
        except ValueError as e:
            await client.reply(message, str(e))
            return
        except Exception:  # noqa: BLE001
            log.exception("supplement edit failed")
            await client.reply(message, "Не получилось дополнить. Попробуй /правка.")
            return
        await client.reply(message, f"Добавил к последней операции — {changed}")

    return {
        "start": handle_start,
        "help": handle_help,
        "version": handle_version,
        "link": handle_link,
        "setup": handle_setup,
        "today": handle_today,
        "last": handle_last,
        "undo": handle_undo,
        "edit": handle_edit,
        "cancel": handle_cancel,
        "stock": handle_stock,
        "repair": handle_repair,
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
