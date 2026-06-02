"""Application context — singleton с инстанциями всех слоёв.

Создаётся в main.py и передаётся в хендлеры через замыкания.
Изолирует тесты от глобального state.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.canonicalize import ProductCatalog
from src.config.settings import settings
from src.dialog.engine import DialogEngine
from src.llm.base import LLMParser
from src.stt.base import STTEngine
from src.storage import (
    CategoriesCacheRepo,
    ChatSheetsRepo,
    DedupRepo,
    DialogRepo,
    IdempotencyRepo,
    LocationsCacheRepo,
    OperationsLogRepo,
    PendingWritesRepo,
    PinAttemptsRepo,
    ProductsCacheRepo,
    open_initialized,
)

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    db: sqlite3.Connection
    chat_sheets: ChatSheetsRepo
    idempotency: IdempotencyRepo
    dedup: DedupRepo
    dialog: DialogRepo
    operations_log: OperationsLogRepo
    pending_writes: PendingWritesRepo
    products_cache: ProductsCacheRepo
    locations_cache: LocationsCacheRepo
    categories_cache: CategoriesCacheRepo
    pin_attempts: PinAttemptsRepo
    catalog: ProductCatalog
    dialog_engine: DialogEngine
    llm_parser: Optional[LLMParser] = None
    stt_engine: Optional[STTEngine] = None

    @classmethod
    def bootstrap(cls, with_llm: bool = True, with_stt: bool = True) -> "AppContext":
        """Создать контекст с реальными слоями. Используется в main.py."""
        db = open_initialized(settings.db_path)

        # Каталог товаров: из импорта прайса
        products_import = Path(settings.products_import_path)
        if products_import.exists():
            catalog = ProductCatalog.from_import_json(products_import)
            log.info("Каталог товаров загружен: %d канонов", catalog.size())
        else:
            log.warning(
                "Файл импорта прайса не найден: %s — каталог пуст. "
                "Запусти /setup для инициализации.",
                products_import,
            )
            catalog = ProductCatalog([])

        # Известные продукты и точки для DialogEngine (canonicalize step)
        known_products = {e.canon.lower() for e in catalog._entries}
        known_locations = {"магазин зинино", "магазин кармалы"}

        dialog_engine = DialogEngine(
            known_product_canons=known_products,
            known_locations=known_locations,
        )

        llm_parser = None
        if with_llm:
            try:
                from src.llm.factory import get_parser
                llm_parser = get_parser()
                log.info("LLM-парсер активен: %s", llm_parser.name)
            except Exception:  # noqa: BLE001
                log.exception("LLM-парсер не инициализирован")

        stt_engine = None
        if with_stt:
            try:
                from src.stt.factory import get_engine
                stt_engine = get_engine()
                log.info("STT активен: %s", stt_engine.name)
            except Exception:  # noqa: BLE001
                log.exception("STT не инициализирован — голосовые работать не будут")

        return cls(
            db=db,
            chat_sheets=ChatSheetsRepo(db),
            idempotency=IdempotencyRepo(db),
            dedup=DedupRepo(db),
            dialog=DialogRepo(db),
            operations_log=OperationsLogRepo(db),
            pending_writes=PendingWritesRepo(db),
            products_cache=ProductsCacheRepo(db),
            locations_cache=LocationsCacheRepo(db),
            categories_cache=CategoriesCacheRepo(db),
            pin_attempts=PinAttemptsRepo(db),
            catalog=catalog,
            dialog_engine=dialog_engine,
            llm_parser=llm_parser,
            stt_engine=stt_engine,
        )
