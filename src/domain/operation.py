from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


# === Enums ===

class PaymentMethod(StrEnum):
    CASH = "наличные"
    CARD = "карта"
    TRANSFER = "счёт"
    UNKNOWN = "не указано"


class ExpenseCategory(StrEnum):
    GOODS_PURCHASE = "закупка товара"
    RENT = "аренда помещения"
    SALARY = "зарплата"
    UTILITIES = "коммунальные / связь"
    MARKETING = "реклама / маркетинг"
    TRANSPORT = "транспорт / доставка"
    TAXES_BANK = "налоги / банк / эквайринг"
    EQUIPMENT_REPAIR = "оборудование / ремонт"
    OTHER = "прочее"
    # not-expense-but-used as category for symmetry
    DEPOSIT = "внесение"
    WITHDRAWAL = "изъятие"
    OTHER_INCOME = "прочий приход"
    SALE = "продажа"
    RETURN_TO_CUSTOMER = "возврат покупателю"
    RETURN_FROM_SUPPLIER = "возврат поставщика"


class CashflowType(StrEnum):
    EXPENSE = "расход"
    OTHER_INCOME = "прочий приход"
    DEPOSIT = "внесение"
    WITHDRAWAL = "изъятие"


class TopMetric(StrEnum):
    REVENUE = "по выручке"  # дефолт для магазина
    PROFIT = "по прибыли"
    QUANTITY = "по количеству"


class ReportPeriodType(StrEnum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    CUSTOM = "custom"


# === Базовые сущности ===

class Confidence(BaseModel):
    text: float = Field(ge=0.0, le=1.0)
    amount: float = Field(ge=0.0, le=1.0, default=1.0)
    quantity: float = Field(ge=0.0, le=1.0, default=1.0)

    @property
    def critical(self) -> float:
        return min(self.text, self.amount, self.quantity)


class GoodsLine(BaseModel):
    product: str
    qty: float = Field(gt=0)
    unit: str
    price_per_unit_kopecks: int | None = None
    comment: str | None = None


# === Операции с одновременным движением денег и товаров ===

class Sale(BaseModel):
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    counterparty: str | None = None
    location: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class Purchase(BaseModel):
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    supplier: str
    location: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class ReturnFromCustomer(BaseModel):
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    customer: str | None = None
    location: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class ReturnToSupplier(BaseModel):
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    supplier: str
    location: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


# === Операции только с деньгами или только с товарами ===

class Cashflow(BaseModel):
    occurred_at: datetime
    op_type: CashflowType
    amount_kopecks: int = Field(gt=0)
    category: ExpenseCategory
    counterparty: str | None = None
    location: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    description: str
    confidence: Confidence
    raw_text: str


class Writeoff(BaseModel):
    occurred_at: datetime
    lines: list[GoodsLine] = Field(min_length=1)
    location: str
    reason: str
    confidence: Confidence
    raw_text: str


class Movement(BaseModel):
    occurred_at: datetime
    lines: list[GoodsLine] = Field(min_length=1)
    from_location: str
    to_location: str
    confidence: Confidence
    raw_text: str


class InventoryAdjustment(BaseModel):
    occurred_at: datetime
    product: str
    location: str
    actual_qty: float = Field(ge=0)
    unit: str
    confidence: Confidence
    raw_text: str


# === Multi-ops ===

class SalesBatch(BaseModel):
    sales: list[Sale] = Field(min_length=2)
    raw_text: str


# === Запросы ===

class StockQuery(BaseModel):
    product: str | None = None
    location: str | None = None


class ReportPeriodRequest(BaseModel):
    period_type: ReportPeriodType
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    quarter: int | None = Field(default=None, ge=1, le=4)
    relative: Literal["current", "previous", None] = None
    top_metric: TopMetric = TopMetric.REVENUE
    location_filter: str | None = None
    period_is_clear: bool


# === Канонизация и правки ===

class ProductCanonicalization(BaseModel):
    decision: Literal["existing", "new"]
    canon: str | None = None
    new_canon: str | None = None
    default_unit: str | None = None


class LocationCanonicalization(BaseModel):
    decision: Literal["existing", "new"]
    canon: str | None = None
    new_canon: str | None = None
    location_type: Literal["магазин", "склад", None] = None


class EditLastRequest(BaseModel):
    field: Literal["amount", "qty", "counterparty", "category", "location", "payment", "description"]
    new_value: str | int | float


# === Уточнение ===

IntentHint = Literal[
    "sale", "purchase", "return_customer", "return_supplier",
    "expense", "writeoff", "movement", "report", None,
]


class ClarificationNeeded(BaseModel):
    raw_text: str
    reason: str
    question: str
    intent_hint: IntentHint = None


# === Дискриминированный union ===

ParsedCommand = (
    Sale | Purchase | ReturnFromCustomer | ReturnToSupplier
    | Cashflow | Writeoff | Movement | InventoryAdjustment
    | SalesBatch
    | StockQuery
    | ReportPeriodRequest
    | ProductCanonicalization | LocationCanonicalization
    | EditLastRequest
    | ClarificationNeeded
)


# === Отчёты ===

class TopItem(BaseModel):
    name: str
    metric_value_kopecks: int | None = None
    metric_qty: float | None = None
    revenue_kopecks: int = 0
    cost_kopecks: int = 0


class FinancialReport(BaseModel):
    period_label: str
    sales_kopecks: int
    sales_count: int
    purchases_kopecks: int
    expenses_kopecks: int
    expenses_breakdown: dict[str, int] = Field(default_factory=dict)
    returns_from_customers_kopecks: int = 0
    returns_to_suppliers_kopecks: int = 0
    deposits_kopecks: int = 0
    withdrawals_kopecks: int = 0
    top_products: list[TopItem] = Field(default_factory=list, max_length=3)
    top_locations: list[TopItem] = Field(default_factory=list, max_length=5)
    top_metric: TopMetric = TopMetric.REVENUE

    @property
    def cash_balance_kopecks(self) -> int:
        return (
            self.sales_kopecks
            + self.returns_to_suppliers_kopecks
            + self.deposits_kopecks
            - self.purchases_kopecks
            - self.expenses_kopecks
            - self.returns_from_customers_kopecks
            - self.withdrawals_kopecks
        )


class StockSnapshot(BaseModel):
    product: str
    unit: str
    location: str
    qty: float
    avg_purchase_price_kopecks: int | None = None
    updated_at: datetime


class StockReport(BaseModel):
    items: list[StockSnapshot]
    product_filter: str | None = None
    location_filter: str | None = None
