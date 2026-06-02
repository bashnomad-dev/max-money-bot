"""Доменные типы (pydantic v2). Соответствует docs/data-model.md §2."""
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Location(StrEnum):
    ZININO = "Магазин Зинино"
    KARMALY = "Магазин Кармалы"


class PaymentMethod(StrEnum):
    CASH = "наличные"
    CARD = "карта"
    TRANSFER = "счёт"
    UNKNOWN = "не указано"


class Confidence(BaseModel):
    text: float = Field(ge=0.0, le=1.0)
    amount: float = Field(default=1.0, ge=0.0, le=1.0)
    quantity: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def critical(self) -> float:
        return min(self.text, self.amount, self.quantity)


class GoodsLine(BaseModel):
    name: str
    qty: float = Field(gt=0)
    unit: str
    price_per_unit_rub: float | None = None
    comment: str | None = None


# === Операции ===

class Sale(BaseModel):
    tx_id: str
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    location: Location
    customer: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    comment: str | None = None
    confidence: Confidence
    raw_text: str


class Purchase(BaseModel):
    tx_id: str
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    supplier: str
    lines: list[GoodsLine] = Field(min_length=1)
    destination: Location
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    comment: str | None = None
    confidence: Confidence
    raw_text: str


class ReturnDirection(StrEnum):
    FROM_CUSTOMER = "from_customer"
    TO_SUPPLIER = "to_supplier"


class Return(BaseModel):
    tx_id: str
    direction: ReturnDirection
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    counterparty: str
    lines: list[GoodsLine] = Field(min_length=1)
    location: Location
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    comment: str | None = None
    confidence: Confidence
    raw_text: str


class CashflowType(StrEnum):
    EXPENSE = "расход"
    OTHER_INCOME = "прочий приход"
    DEPOSIT = "внесение"
    WITHDRAWAL = "изъятие"


class ExpenseCategory(StrEnum):
    GOODS_PURCHASE = "закупка товара"
    RENT = "аренда помещения"
    SALARY = "зарплата"
    UTILITIES = "коммунальные / связь"
    MARKETING = "реклама / маркетинг"
    TRANSPORT = "транспорт / доставка"
    TAXES_BANK = "налоги / банк / эквайринг"
    EQUIPMENT = "оборудование / ремонт"
    OTHER = "прочее"


class Cashflow(BaseModel):
    tx_id: str
    occurred_at: datetime
    op_type: CashflowType
    amount_kopecks: int = Field(gt=0)
    description: str
    category: ExpenseCategory | None = None
    counterparty: str | None = None
    location: Location | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class WriteoffOrMovementType(StrEnum):
    WRITEOFF = "списание"
    MOVEMENT = "перемещение"


class WriteoffOrMovement(BaseModel):
    tx_id: str
    occurred_at: datetime
    op_type: WriteoffOrMovementType
    location: Location | None = None      # для writeoff
    source: Location | None = None        # для movement
    destination: Location | None = None   # для movement
    lines: list[GoodsLine] = Field(min_length=1)
    comment: str | None = None
    confidence: Confidence
    raw_text: str


class InventoryFact(BaseModel):
    name: str
    qty: float = Field(ge=0)  # 0 = товар закончился
    unit: str


class Inventory(BaseModel):
    tx_id: str
    occurred_at: datetime
    location: Location
    facts: list[InventoryFact] = Field(min_length=1)
    confidence: Confidence
    raw_text: str


# === Запросы и уточнения ===

class StockQuery(BaseModel):
    product_query: str | None = None
    location: Location | None = None


class ReportPeriodType(StrEnum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    CUSTOM = "custom"


class TopMetric(StrEnum):
    REVENUE = "выручка"
    PROFIT = "прибыль"
    QUANTITY = "количество"


class PeriodReportRequest(BaseModel):
    period_type: ReportPeriodType
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    quarter: int | None = Field(default=None, ge=1, le=4)
    relative: Literal["current", "previous", None] = None
    location: Location | None = None
    top_metric: TopMetric = TopMetric.REVENUE
    period_is_clear: bool


class ClarificationNeeded(BaseModel):
    raw_text: str
    reason: str
    question: str
    intent_hint: Literal["sale", "purchase", "return", "cashflow",
                         "writeoff", "inventory", "report", None] = None


# Дискриминированный union, который возвращает парсер
ParsedCommand = (
    Sale | Purchase | Return | Cashflow | WriteoffOrMovement
    | Inventory | StockQuery | PeriodReportRequest | ClarificationNeeded
)


# === Остатки и отчёты (для read-side) ===

class StockItem(BaseModel):
    product: str
    location: Location
    qty: float
    unit: str
    avg_cost_kopecks: int = 0
    updated_at: datetime


class TopItem(BaseModel):
    label: str
    revenue_kopecks: int = 0
    profit_kopecks: int = 0
    quantity: float = 0


class FinancialReport(BaseModel):
    period_label: str
    income_kopecks: int = 0
    expense_kopecks: int = 0
    income_count: int = 0
    expense_count: int = 0
    by_location: dict[Location, int] = Field(default_factory=dict)
    top_products: list[TopItem] = Field(default_factory=list)
    top_locations: list[TopItem] = Field(default_factory=list)
    top_metric: TopMetric = TopMetric.REVENUE

    @property
    def balance_kopecks(self) -> int:
        return self.income_kopecks - self.expense_kopecks
