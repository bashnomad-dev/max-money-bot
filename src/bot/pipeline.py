"""Основной pipeline: распарсенный текст → запись в Sheets с применением UX-правил.

Используется и из обработчика голоса, и из обработчика текста.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.bot.context import AppContext
from src.bot.text_responses import (
    CARD_DEDUP_MSG,
    CARD_LARGE_AMOUNT_MSG,
    CARD_LOW_CONFIDENCE_MSG,
    DUPLICATE_MSG,
    LLM_DOWN_MSG,
    NEED_LINK_MSG,
    SHEETS_DOWN_MSG,
    WROTE_FALLBACK_TEXT_MSG,
    WROTE_REACTION,
)
from src.canonicalize import canonicalize_unit
from src.config.settings import settings
from src.dialog.engine import DialogResult, DialogStep
from src.dialog.semantic_hash import semantic_hash
from src.domain.operation import (
    Cashflow,
    ClarificationNeeded,
    Inventory,
    Location,
    PeriodReportRequest,
    Purchase,
    Return,
    Sale,
    StockQuery,
    WriteoffOrMovement,
)
from src.reports.daily import build_daily_report, format_daily_report
from src.reports.period import build_period_report, format_period_report
from src.reports.stock import format_stock_report
from src.sheets.writer import (
    write_cashflow,
    write_inventory,
    write_purchase,
    write_return,
    write_sale,
    write_writeoff_or_movement,
)

log = logging.getLogger(__name__)


def _canonicalize_lines(op: Any) -> None:
    """Применить канонизацию единиц к строкам операции (in-place)."""
    if not hasattr(op, "lines") or not op.lines:
        return
    for line in op.lines:
        canon_unit = canonicalize_unit(line.unit)
        if canon_unit:
            line.unit = canon_unit


def _open_spreadsheet_for_chat(ctx: AppContext, chat_id: str):
    """Открыть Google Spreadsheet по привязанной к чату таблице."""
    sheet_id = ctx.chat_sheets.get_sheet_id(chat_id) or settings.default_sheet_id
    if not sheet_id:
        return None
    from src.sheets.setup import open_sheet
    return open_sheet(sheet_id)


async def process_parsed(
    ctx: AppContext,
    parsed: Any,
    chat_id: str,
    user_id: str,
    message_id: str,
) -> str:
    """Главный pipeline. Возвращает текст для пользователя (либо WROTE_REACTION-маркер)."""

    # Идемпотентность по message_id
    prev = ctx.idempotency.seen(message_id)
    if prev == "written":
        return DUPLICATE_MSG

    # Применяем канонизацию единиц на месте
    _canonicalize_lines(parsed)

    # === Чтения (не пишут в Sheets) ===

    if isinstance(parsed, ClarificationNeeded):
        return parsed.question

    if isinstance(parsed, StockQuery):
        spreadsheet = _open_spreadsheet_for_chat(ctx, chat_id)
        if spreadsheet is None:
            return NEED_LINK_MSG
        return format_stock_report(spreadsheet, parsed.product_query, parsed.location.value if parsed.location else None)

    if isinstance(parsed, PeriodReportRequest):
        spreadsheet = _open_spreadsheet_for_chat(ctx, chat_id)
        if spreadsheet is None:
            return NEED_LINK_MSG
        if not parsed.period_is_clear:
            period_word = {"month": "месяц", "quarter": "квартал", "year": "год"}.get(
                parsed.period_type.value, "период"
            )
            return f"За какой {period_word} сделать отчёт: за текущий или за конкретный?"
        rep = build_period_report(
            spreadsheet,
            period_type=parsed.period_type.value,
            year=parsed.year,
            month=parsed.month,
            quarter=parsed.quarter,
            relative=parsed.relative,
            location_filter=parsed.location.value if parsed.location else None,
            top_metric=parsed.top_metric.value,
            today=date.today(),
        )
        return format_period_report(rep)

    # === Запись ===

    # Семантический дедуп
    semhash = None
    dedup_match = None
    if isinstance(parsed, (Sale, Purchase, Return, Cashflow, WriteoffOrMovement)):
        semhash = semantic_hash(parsed)
        dedup_match = ctx.dedup.find(semhash, chat_id)

    # Решение UX
    decision = ctx.dialog_engine.decide(parsed, existing_dedup_match=dedup_match)

    if decision.step == DialogStep.CARD:
        # Сохраняем диалог для последующего подтверждения
        ctx.dialog.set(
            chat_id,
            intent=f"confirm_{type(parsed).__name__.lower()}",
            partial_data={"parsed_class": type(parsed).__name__, "parsed_json": parsed.model_dump(mode='json')},
            ttl_minutes=settings.dialog_state_ttl_minutes,
        )
        summary = _summary_for_card(parsed)
        return CARD_LOW_CONFIDENCE_MSG.format(summary=summary)

    if decision.step == DialogStep.LARGE_AMOUNT_CARD:
        ctx.dialog.set(
            chat_id,
            intent=f"confirm_large_{type(parsed).__name__.lower()}",
            partial_data={"parsed_class": type(parsed).__name__, "parsed_json": parsed.model_dump(mode='json')},
            ttl_minutes=settings.dialog_state_ttl_minutes,
        )
        return CARD_LARGE_AMOUNT_MSG.format(summary=_summary_for_card(parsed))

    if decision.step == DialogStep.DEDUP_CHECK:
        ctx.dialog.set(
            chat_id,
            intent="confirm_dedup",
            partial_data={
                "parsed_class": type(parsed).__name__,
                "parsed_json": parsed.model_dump(mode='json'),
                "previous_summary": dedup_match["operation_summary"],
            },
            ttl_minutes=settings.dialog_state_ttl_minutes,
        )
        when = _relative_time(dedup_match["created_at"])
        return CARD_DEDUP_MSG.format(when=when, previous=dedup_match["operation_summary"])

    if decision.step == DialogStep.CANONICALIZE:
        # Найдём кандидатов и сохраним диалог
        candidates = []
        for line in parsed.lines:
            matches = ctx.catalog.lookup(line.name, top_k=3, min_score=0.5)
            candidates.extend([m.canon for m in matches])
        ctx.dialog.set(
            chat_id,
            intent="canonicalize_product",
            partial_data={
                "parsed_class": type(parsed).__name__,
                "parsed_json": parsed.model_dump(mode='json'),
                "candidates": candidates,
            },
            ttl_minutes=settings.dialog_state_ttl_minutes,
        )
        # Формируем сообщение
        if candidates:
            options = "\n".join(f"  {i}. {c}" for i, c in enumerate(candidates, 1))
            return f"Не нашёл точное совпадение в каталоге. Похожие:\n{options}\n\nОтветь номером или «новый»."
        return "Не нашёл в каталоге. Завести как новый товар? Ответь «да» или «нет»."

    if decision.step == DialogStep.WRITE:
        return await _do_write(ctx, parsed, chat_id, user_id, message_id, semhash)

    if decision.step == DialogStep.CLARIFY:
        return decision.message or "Уточни, пожалуйста."

    return f"Не знаю что делать с {decision.step.value}"


async def _do_write(
    ctx: AppContext,
    parsed: Any,
    chat_id: str,
    user_id: str,
    message_id: str,
    semhash: str | None,
) -> str:
    """Физическая запись в Sheets + регистрация в operations_log + dedup."""
    spreadsheet = _open_spreadsheet_for_chat(ctx, chat_id)
    if spreadsheet is None:
        return NEED_LINK_MSG

    try:
        result = _dispatch_write(spreadsheet, parsed)
    except Exception as e:  # noqa: BLE001
        log.exception("Sheets write failed")
        # Очередь pending_writes
        ctx.pending_writes.enqueue(
            chat_id,
            {
                "parsed_class": type(parsed).__name__,
                "parsed_json": parsed.model_dump(mode='json'),
            },
            error=str(e),
        )
        return SHEETS_DOWN_MSG

    # Лог в operations_log
    ctx.operations_log.log(
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        tx_id=result.tx_id,
        op_kind=result.op_kind,
        sheet_refs=result.refs_as_dicts(),
        summary=result.summary,
    )

    # Идемпотентность
    ctx.idempotency.mark(message_id, chat_id, user_id, "written")

    # Семантический дедуп
    if semhash:
        ctx.dedup.insert(
            semhash, chat_id, result.summary, result.refs_as_dicts(),
            ttl_minutes=settings.dedup_window_minutes,
        )

    # TODO: апдейт листа «Остатки» через src.stock.sheets_sync.sync_after_op
    # (отложено до интеграционного теста с реальной Sheets — там доделаем)

    # Возвращаем маркер «реакция» (хендлер сам поставит ✅) либо текст
    return WROTE_REACTION  # маркер для хендлера


def _dispatch_write(spreadsheet, op: Any):
    if isinstance(op, Sale):
        return write_sale(spreadsheet, op)
    if isinstance(op, Purchase):
        return write_purchase(spreadsheet, op)
    if isinstance(op, Return):
        return write_return(spreadsheet, op)
    if isinstance(op, Cashflow):
        return write_cashflow(spreadsheet, op)
    if isinstance(op, WriteoffOrMovement):
        return write_writeoff_or_movement(spreadsheet, op)
    if isinstance(op, Inventory):
        # expected_stock пустой при первой реализации — позже подтянем из listа Остатки
        return write_inventory(spreadsheet, op, expected_stock={})
    raise TypeError(f"Не поддерживаемый тип для записи: {type(op).__name__}")


def _summary_for_card(parsed: Any) -> str:
    """Краткое описание операции для карточки подтверждения."""
    if isinstance(parsed, Sale):
        lines = ", ".join(f"{l.name} {l.qty}{l.unit}" for l in parsed.lines)
        return f"💰 Продажа {parsed.amount_kopecks//100}₽ ({lines}) на {parsed.location.value}, {parsed.payment.value}"
    if isinstance(parsed, Purchase):
        lines = ", ".join(f"{l.name} {l.qty}{l.unit}" for l in parsed.lines)
        return f"📦 Закупка {parsed.amount_kopecks//100}₽ от {parsed.supplier} ({lines}) на {parsed.destination.value}"
    if isinstance(parsed, Cashflow):
        loc = f" на {parsed.location.value}" if parsed.location else ""
        return f"💸 {parsed.op_type.value} {parsed.amount_kopecks//100}₽ — {parsed.description}{loc}"
    if isinstance(parsed, Return):
        direction = "от" if parsed.direction.value == "from_customer" else "к"
        lines = ", ".join(f"{l.name} {l.qty}{l.unit}" for l in parsed.lines)
        return f"↩️ Возврат {direction} {parsed.counterparty}: {lines} на {parsed.amount_kopecks//100}₽"
    if isinstance(parsed, WriteoffOrMovement):
        lines = ", ".join(f"{l.name} {l.qty}{l.unit}" for l in parsed.lines)
        if parsed.op_type.value == "перемещение":
            return f"🔄 Перемещение {parsed.source.value} → {parsed.destination.value}: {lines}"
        return f"🗑 Списание ({parsed.comment or ''}): {lines}"
    return repr(parsed)[:200]


def _relative_time(iso_str: str) -> str:
    """Грубо: 'минуту', 'N минут', '1 час'..."""
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    diff = datetime.utcnow() - dt
    minutes = max(0, int(diff.total_seconds() // 60))
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    return f"{hours} ч"
