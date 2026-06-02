"""Google Sheets-слой: схема, инициализация, маппинг ParsedCommand → строки."""
from src.sheets.schema import (
    DEFAULT_CATEGORIES,
    DEFAULT_LOCATIONS,
    SHEET_CATEGORIES,
    SHEET_GOODS,
    SHEET_LOCATIONS,
    SHEET_MONEY,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SPECS,
    SheetSpec,
)
from src.sheets.setup import SheetsSetupError, setup_sheet
from src.sheets.writer import (
    SheetRowRef,
    WriteResult,
    undo_by_refs,
    write_cashflow,
    write_inventory,
    write_purchase,
    write_return,
    write_sale,
    write_writeoff_or_movement,
)

__all__ = [
    "SheetRowRef",
    "WriteResult",
    "undo_by_refs",
    "write_cashflow",
    "write_inventory",
    "write_purchase",
    "write_return",
    "write_sale",
    "write_writeoff_or_movement",
    "DEFAULT_CATEGORIES",
    "DEFAULT_LOCATIONS",
    "SHEET_CATEGORIES",
    "SHEET_GOODS",
    "SHEET_LOCATIONS",
    "SHEET_MONEY",
    "SHEET_PRODUCTS",
    "SHEET_STOCK",
    "SPECS",
    "SheetSpec",
    "SheetsSetupError",
    "setup_sheet",
]
