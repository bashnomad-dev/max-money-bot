"""Запись ParsedCommand в Google Sheets (3 листа транзакционно через общий tx_id).

Стратегия (SPEC §14.6):
  1. Сначала "Движение товаров" (если есть товарная часть).
  2. Потом "Движение денег" (если есть денежная часть).
  3. Потом обновляем "Остатки".
  4. На каждом шаге собираем SheetRowRef для последующего /undo.
  5. При сбое — компенсация (удалить уже записанные) и enqueue в pending_writes.

Каждая запись возвращает WriteResult с tx_id и списком sheet_refs для логирования.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.settings import settings
from src.domain.operation import (
    Cashflow,
    GoodsLine,
    Inventory,
    Location,
    Purchase,
    Return,
    ReturnDirection,
    Sale,
    WriteoffOrMovement,
    WriteoffOrMovementType,
)
from src.sheets.schema import (
    GOODS_HEADERS,
    MONEY_HEADERS,
    SHEET_GOODS,
    SHEET_MONEY,
)

log = logging.getLogger(__name__)


# ============================================================
# Типы операций для строк (соответствуют data-model.md §1.4, §1.6)
# ============================================================

MONEY_OP_SALE = "продажа"
MONEY_OP_PURCHASE = "закупка"
MONEY_OP_EXPENSE = "расход"
MONEY_OP_OTHER_INCOME = "прочий приход"
MONEY_OP_RETURN_TO_CUSTOMER = "возврат покупателю"
MONEY_OP_RETURN_FROM_SUPPLIER = "возврат поставщика"
MONEY_OP_DEPOSIT = "внесение"
MONEY_OP_WITHDRAWAL = "изъятие"

GOODS_OP_RECEIVE = "поступление"
GOODS_OP_SALE = "продажа"
GOODS_OP_WRITEOFF = "списание"
GOODS_OP_RETURN_BY_CUSTOMER = "возврат покупателя"
GOODS_OP_RETURN_TO_SUPPLIER = "возврат поставщику"
GOODS_OP_MOVEMENT = "перемещение"
GOODS_OP_INVENTORY = "инвентаризация"


@dataclass
class SheetRowRef:
    sheet: str
    row_index: int

    def to_dict(self) -> dict[str, Any]:
        return {"sheet": self.sheet, "row_index": self.row_index}


@dataclass
class WriteResult:
    tx_id: str
    op_kind: str
    refs: list[SheetRowRef] = field(default_factory=list)
    summary: str = ""

    def refs_as_dicts(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.refs]


# ============================================================
# Утилиты для формата
# ============================================================

def _date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")


def _time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _rub_from_kopecks(kopecks: int) -> int:
    return kopecks // 100


def _fmt_qty(q: float) -> str:
    """Целое без хвоста, дробное — с запятой (РФ-стиль)."""
    if q == int(q):
        return str(int(q))
    return f"{q:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _ru_unit(unit: str) -> str:
    return unit or "не указано"


def _safe(v: Any) -> str:
    return "не указано" if v is None or v == "" else str(v)


def _esc(v: Any) -> Any:
    """Экранировать текст, который Sheets при USER_ENTERED примет за формулу.

    Имена/комментарии, начинающиеся с = + - @, иначе превращаются в #ERROR!.
    Ведущий апостроф форсит текстовый формат и в самой ячейке не отображается.
    """
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


# ============================================================
# Низкоуровневая запись в Sheets с компенсацией
# ============================================================

def _append_row(spreadsheet, sheet_name: str, row_values: list[Any]) -> int:
    """Append-row через gspread API. Возвращает индекс новой строки (1-based)."""
    ws = spreadsheet.worksheet(sheet_name)
    # append_row возвращает gspread.ValueRange; быстрее через append_rows
    ws.append_rows([row_values], value_input_option="USER_ENTERED")
    # Индекс новой строки = текущее количество заполненных строк
    return len(ws.col_values(1))


def _delete_row(spreadsheet, sheet_name: str, row_index: int) -> None:
    """Откат строки при компенсации."""
    ws = spreadsheet.worksheet(sheet_name)
    ws.delete_rows(row_index)


# ============================================================
# Сборка строк под каждый тип операции
# ============================================================

def _money_row(
    occurred_at: datetime,
    op_type: str,
    amount_rub: int,
    description: str,
    category: str | None,
    counterparty: str | None,
    location: Location | None,
    payment: str,
    tx_id: str,
) -> list[Any]:
    """Собрать строку для листа «Движение денег» в порядке MONEY_HEADERS."""
    return [
        _date(occurred_at),
        _time(occurred_at),
        op_type,
        amount_rub,
        _esc(description or ""),
        _safe(category) if category else "",
        _esc(_safe(counterparty)),
        _safe(location.value if location else None),
        payment,
        tx_id,
    ]


def _goods_row(
    occurred_at: datetime,
    op_type: str,
    location: Location | None,
    source: Location | None,
    line: GoodsLine,
    counterparty: str | None,
    comment: str | None,
    tx_id: str,
) -> list[Any]:
    """Собрать строку для «Движение товаров» в порядке GOODS_HEADERS."""
    return [
        _date(occurred_at),
        _time(occurred_at),
        op_type,
        _safe(location.value if location else None),
        source.value if source else "",
        _esc(line.name),
        line.qty,
        _ru_unit(line.unit),
        line.price_per_unit_rub if line.price_per_unit_rub is not None else "",
        _esc(_safe(counterparty)),
        _esc(line.comment or comment or ""),
        tx_id,
    ]


# ============================================================
# Публичные функции записи
# ============================================================

def write_sale(spreadsheet, op: Sale) -> WriteResult:
    """Sale → товары (расход со склада) + деньги (приход)."""
    result = WriteResult(tx_id=op.tx_id, op_kind="sale")
    try:
        for line in op.lines:
            row_idx = _append_row(
                spreadsheet,
                SHEET_GOODS,
                _goods_row(
                    occurred_at=op.occurred_at,
                    op_type=GOODS_OP_SALE,
                    location=op.location,
                    source=None,
                    line=line,
                    counterparty=op.customer,
                    comment=op.comment,
                    tx_id=op.tx_id,
                ),
            )
            result.refs.append(SheetRowRef(SHEET_GOODS, row_idx))

        money_row_idx = _append_row(
            spreadsheet,
            SHEET_MONEY,
            _money_row(
                occurred_at=op.occurred_at,
                op_type=MONEY_OP_SALE,
                amount_rub=_rub_from_kopecks(op.amount_kopecks),
                description=", ".join(f"{l.name} {_fmt_qty(l.qty)} {l.unit}" for l in op.lines),
                category=None,
                counterparty=op.customer,
                location=op.location,
                payment=op.payment.value,
                tx_id=op.tx_id,
            ),
        )
        result.refs.append(SheetRowRef(SHEET_MONEY, money_row_idx))

        lines_str = ", ".join(f"{l.name} {_fmt_qty(l.qty)}{l.unit}" for l in op.lines)
        result.summary = f"продажа {_rub_from_kopecks(op.amount_kopecks)}₽ ({lines_str}) на {op.location.value}"
        return result
    except Exception:
        _compensate(spreadsheet, result.refs)
        raise


def write_purchase(spreadsheet, op: Purchase) -> WriteResult:
    """Purchase → товары (поступление) + деньги (расход)."""
    result = WriteResult(tx_id=op.tx_id, op_kind="purchase")
    try:
        for line in op.lines:
            row_idx = _append_row(
                spreadsheet,
                SHEET_GOODS,
                _goods_row(
                    occurred_at=op.occurred_at,
                    op_type=GOODS_OP_RECEIVE,
                    location=op.destination,
                    source=None,
                    line=line,
                    counterparty=op.supplier,
                    comment=op.comment,
                    tx_id=op.tx_id,
                ),
            )
            result.refs.append(SheetRowRef(SHEET_GOODS, row_idx))

        money_row_idx = _append_row(
            spreadsheet,
            SHEET_MONEY,
            _money_row(
                occurred_at=op.occurred_at,
                op_type=MONEY_OP_PURCHASE,
                amount_rub=_rub_from_kopecks(op.amount_kopecks),
                description=", ".join(f"{l.name} {_fmt_qty(l.qty)} {l.unit}" for l in op.lines),
                category="закупка товара",
                counterparty=op.supplier,
                location=op.destination,
                payment=op.payment.value,
                tx_id=op.tx_id,
            ),
        )
        result.refs.append(SheetRowRef(SHEET_MONEY, money_row_idx))

        lines_str = ", ".join(f"{l.name} {_fmt_qty(l.qty)}{l.unit}" for l in op.lines)
        result.summary = f"закупка {_rub_from_kopecks(op.amount_kopecks)}₽ от {op.supplier} ({lines_str}) на {op.destination.value}"
        return result
    except Exception:
        _compensate(spreadsheet, result.refs)
        raise


def write_return(spreadsheet, op: Return) -> WriteResult:
    """Возврат: from_customer → товар +, деньги -; to_supplier → товар -, деньги +."""
    result = WriteResult(tx_id=op.tx_id, op_kind="return")
    try:
        if op.direction == ReturnDirection.FROM_CUSTOMER:
            goods_op = GOODS_OP_RETURN_BY_CUSTOMER
            money_op = MONEY_OP_RETURN_TO_CUSTOMER
        else:
            goods_op = GOODS_OP_RETURN_TO_SUPPLIER
            money_op = MONEY_OP_RETURN_FROM_SUPPLIER

        for line in op.lines:
            row_idx = _append_row(
                spreadsheet,
                SHEET_GOODS,
                _goods_row(
                    occurred_at=op.occurred_at,
                    op_type=goods_op,
                    location=op.location,
                    source=None,
                    line=line,
                    counterparty=op.counterparty,
                    comment=op.comment,
                    tx_id=op.tx_id,
                ),
            )
            result.refs.append(SheetRowRef(SHEET_GOODS, row_idx))

        money_row_idx = _append_row(
            spreadsheet,
            SHEET_MONEY,
            _money_row(
                occurred_at=op.occurred_at,
                op_type=money_op,
                amount_rub=_rub_from_kopecks(op.amount_kopecks),
                description=", ".join(f"{l.name} {_fmt_qty(l.qty)} {l.unit}" for l in op.lines),
                category=None,
                counterparty=op.counterparty,
                location=op.location,
                payment=op.payment.value,
                tx_id=op.tx_id,
            ),
        )
        result.refs.append(SheetRowRef(SHEET_MONEY, money_row_idx))

        direction_ru = "от покупателя" if op.direction == ReturnDirection.FROM_CUSTOMER else "поставщику"
        result.summary = f"возврат {direction_ru} {op.counterparty} на {_rub_from_kopecks(op.amount_kopecks)}₽"
        return result
    except Exception:
        _compensate(spreadsheet, result.refs)
        raise


def write_cashflow(spreadsheet, op: Cashflow) -> WriteResult:
    """Cashflow — только лист «Движение денег», товары не трогаются."""
    result = WriteResult(tx_id=op.tx_id, op_kind="cashflow")
    money_row_idx = _append_row(
        spreadsheet,
        SHEET_MONEY,
        _money_row(
            occurred_at=op.occurred_at,
            op_type=op.op_type.value,
            amount_rub=_rub_from_kopecks(op.amount_kopecks),
            description=op.description,
            category=op.category.value if op.category else None,
            counterparty=op.counterparty,
            location=op.location,
            payment=op.payment.value,
            tx_id=op.tx_id,
        ),
    )
    result.refs.append(SheetRowRef(SHEET_MONEY, money_row_idx))
    result.summary = (
        f"{op.op_type.value} {_rub_from_kopecks(op.amount_kopecks)}₽ — {op.description}"
    )
    return result


def write_writeoff_or_movement(spreadsheet, op: WriteoffOrMovement) -> WriteResult:
    """Списание или перемещение. Только товары + остатки. Деньги не трогаются."""
    result = WriteResult(tx_id=op.tx_id, op_kind=op.op_type.value)
    try:
        if op.op_type == WriteoffOrMovementType.WRITEOFF:
            for line in op.lines:
                row_idx = _append_row(
                    spreadsheet,
                    SHEET_GOODS,
                    _goods_row(
                        occurred_at=op.occurred_at,
                        op_type=GOODS_OP_WRITEOFF,
                        location=op.location,
                        source=None,
                        line=line,
                        counterparty=None,
                        comment=op.comment,
                        tx_id=op.tx_id,
                    ),
                )
                result.refs.append(SheetRowRef(SHEET_GOODS, row_idx))
            loc_str = op.location.value if op.location else "не указано"
            result.summary = (
                f"списание на {loc_str}: "
                f"{', '.join(f'{l.name} {_fmt_qty(l.qty)}{l.unit}' for l in op.lines)}"
            )
        else:  # MOVEMENT
            # Перемещение = две связанные строки: убытие из source + поступление в destination
            if op.source is None or op.destination is None:
                raise ValueError("Для перемещения нужны source и destination")
            for line in op.lines:
                # Минус с source
                row_out = _append_row(
                    spreadsheet,
                    SHEET_GOODS,
                    _goods_row(
                        occurred_at=op.occurred_at,
                        op_type=GOODS_OP_MOVEMENT,
                        location=op.source,
                        source=None,
                        line=GoodsLine(name=line.name, qty=line.qty, unit=line.unit, comment="↓ перевезено"),
                        counterparty=None,
                        comment=None,
                        tx_id=op.tx_id,
                    ),
                )
                result.refs.append(SheetRowRef(SHEET_GOODS, row_out))
                # Плюс в destination
                row_in = _append_row(
                    spreadsheet,
                    SHEET_GOODS,
                    _goods_row(
                        occurred_at=op.occurred_at,
                        op_type=GOODS_OP_MOVEMENT,
                        location=op.destination,
                        source=op.source,
                        line=GoodsLine(name=line.name, qty=line.qty, unit=line.unit, comment="↑ принято"),
                        counterparty=None,
                        comment=None,
                        tx_id=op.tx_id,
                    ),
                )
                result.refs.append(SheetRowRef(SHEET_GOODS, row_in))
            result.summary = (
                f"перемещение {op.source.value} → {op.destination.value}: "
                f"{', '.join(f'{l.name} {_fmt_qty(l.qty)}{l.unit}' for l in op.lines)}"
            )
        return result
    except Exception:
        _compensate(spreadsheet, result.refs)
        raise


def write_inventory(spreadsheet, op: Inventory, expected_stock: dict[str, float]) -> WriteResult:
    """Запись инвентаризации: для каждого факта вычисляем дельту и пишем корректировку.

    expected_stock: текущие расчётные остатки по {product_canon: qty} на op.location.
    """
    result = WriteResult(tx_id=op.tx_id, op_kind="inventory")
    try:
        for fact in op.facts:
            expected_qty = expected_stock.get(fact.name, 0)
            delta = fact.qty - expected_qty  # положительная = +, отрицательная = списание
            comment = f"инвентаризация: было {_fmt_qty(expected_qty)}, стало {_fmt_qty(fact.qty)}, дельта {_fmt_qty(delta)}"
            row_idx = _append_row(
                spreadsheet,
                SHEET_GOODS,
                _goods_row(
                    occurred_at=op.occurred_at,
                    op_type=GOODS_OP_INVENTORY,
                    location=op.location,
                    source=None,
                    line=GoodsLine(
                        name=fact.name,
                        qty=abs(delta) if delta != 0 else 0.001,  # qty>0 в Pydantic — ставим минимум для нулевой коррекции
                        unit=fact.unit,
                        comment=comment,
                    ),
                    counterparty=None,
                    comment=None,
                    tx_id=op.tx_id,
                ),
            )
            result.refs.append(SheetRowRef(SHEET_GOODS, row_idx))

        result.summary = f"инвентаризация на {op.location.value}: {len(op.facts)} позиций"
        return result
    except Exception:
        _compensate(spreadsheet, result.refs)
        raise


# ============================================================
# Компенсация при сбое
# ============================================================

def _compensate(spreadsheet, refs: list[SheetRowRef]) -> None:
    """Удалить уже записанные строки при сбое. Идём в обратном порядке (последние сверху)."""
    for ref in reversed(refs):
        try:
            _delete_row(spreadsheet, ref.sheet, ref.row_index)
            log.warning("Компенсация: удалена строка %s!%d", ref.sheet, ref.row_index)
        except Exception:  # noqa: BLE001
            log.exception(
                "Не удалось откатить %s!%d — может потребовать ручного вмешательства",
                ref.sheet,
                ref.row_index,
            )


# ============================================================
# Удаление операции по tx_id (для /undo)
# ============================================================

# ============================================================
# Точечная правка последней операции (/edit last)
# ============================================================

# Поле → (заголовок в листе, 1-based номер колонки в «Движении денег»)
EDIT_FIELDS: dict[str, tuple[str, int]] = {
    "сумма": ("Сумма (₽)", 4),
    "контрагент": ("Контрагент", 7),
    "описание": ("Описание", 5),
}


def _parse_amount_rub(value: str) -> int | None:
    raw = value.strip().lower().replace(" ", "").replace("₽", "").replace("р", "")
    mult = 1
    if raw.endswith(("к", "k", "т")):
        mult = 1000
        raw = raw[:-1]
    raw = raw.replace(",", ".")
    try:
        return int(round(float(raw) * mult))
    except ValueError:
        return None


def edit_last_field(spreadsheet, sheet_refs: list[dict[str, Any]], field: str, value: str) -> str:
    """Изменить одно поле последней операции в «Движении денег».

    Возвращает краткое описание изменения. Бросает ValueError при неверном поле/значении.
    """
    fld = field.strip().lower()
    spec = EDIT_FIELDS.get(fld)
    if spec is None:
        raise ValueError(
            f"Неизвестное поле «{field}». Можно править: сумма, контрагент, описание."
        )
    header, col = spec
    money_ref = next((r for r in sheet_refs if r["sheet"] == SHEET_MONEY), None)
    if money_ref is None:
        raise ValueError("У последней операции нет денежной строки — это поле не редактируется.")

    if fld == "сумма":
        amount = _parse_amount_rub(value)
        if amount is None:
            raise ValueError("Сумма должна быть числом, например: /edit last сумма 18000")
        cell_value: Any = amount
    else:
        cell_value = value.strip()

    ws = spreadsheet.worksheet(SHEET_MONEY)
    ws.update_cell(money_ref["row_index"], col, cell_value)
    return f"{header}: {cell_value}"


def undo_by_refs(spreadsheet, refs: list[dict[str, Any]]) -> int:
    """Удалить все строки операции из Sheets. Возвращает количество удалённых.

    Идём в обратном порядке row_index чтобы индексы не съезжали.
    """
    sorted_refs = sorted(refs, key=lambda r: r["row_index"], reverse=True)
    removed = 0
    for ref in sorted_refs:
        try:
            _delete_row(spreadsheet, ref["sheet"], ref["row_index"])
            removed += 1
        except Exception:  # noqa: BLE001
            log.exception("Не смог удалить %s!%d при undo", ref["sheet"], ref["row_index"])
    return removed
