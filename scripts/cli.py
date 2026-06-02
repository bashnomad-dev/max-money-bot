"""CLI runner: текст с консоли → парсер → DialogEngine → опц. запись в мок-таблицу.

Использование:
    # Только парсинг и анализ:
    python -m scripts.cli "Продал 30 мешков цемента за 18 тысяч наличными на Зинино"

    # Интерактивный режим:
    python -m scripts.cli --interactive

    # С реальной записью в мок-Sheets (для демо без GigaChat):
    python -m scripts.cli --mock-llm "Продал 30 мешков цемента за 18к на Зинино"

Запись в реальные Google Sheets выполняется только если задана DEFAULT_SHEET_ID
и есть credentials. Без них использует in-memory мок и показывает что получилось.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# чтобы скрипт запускался как `python -m scripts.cli ...`
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.canonicalize import (
    ProductCatalog,
    canonicalize_location,
    canonicalize_unit,
)
from src.config.settings import settings
from src.dialog.engine import DialogEngine, DialogStep
from src.domain.operation import (
    Cashflow,
    CashflowType,
    Confidence,
    ExpenseCategory,
    GoodsLine,
    Location,
    PaymentMethod,
    Sale,
)

log = logging.getLogger("cli")


def _make_engine_with_evgeny_catalog():
    """Загружает прайс Евгения для канонизации без обращения к Sheets."""
    catalog_path = Path("docs/intake/evgeny/price-normalized.json")
    if not catalog_path.exists():
        return DialogEngine(), None
    catalog = ProductCatalog.from_import_json(catalog_path)
    return DialogEngine(
        known_product_canons={e.canon.lower() for e in catalog._entries},
        known_locations={"магазин зинино", "магазин кармалы"},
    ), catalog


def _mock_parse(text: str) -> Sale | None:
    """Очень упрощённый мок парсера — для демо без GigaChat.

    Распознаёт только базовую продажу с явно указанной суммой и точкой.
    """
    import re
    text_lower = text.lower()
    # Сумма
    m = re.search(r"(\d+)\s*(?:к|тыс|тысяч)", text_lower)
    if not m:
        m = re.search(r"за\s+(\d+)", text_lower)
    if not m:
        return None
    amount_rub = int(m.group(1))
    if "тыс" in text_lower or "к" in text_lower[m.end():m.end()+3]:
        amount_rub *= 1000

    # Точка
    location = canonicalize_location(text)
    if location is None:
        location = Location.ZININO

    # Тип операции
    if not any(kw in text_lower for kw in ("продал", "продажа")):
        return None

    # Количество и товар (грубо)
    qty_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(меш|шт|лист|кубов|квадратов|кг|литров)?", text_lower)
    qty = float(qty_match.group(1).replace(",", ".")) if qty_match else 1
    unit_raw = qty_match.group(2) if qty_match and qty_match.group(2) else "шт"
    unit_canon = canonicalize_unit(unit_raw) or unit_raw

    # Товар: всё между "продал" и "за"
    prod_match = re.search(r"прода(?:л|жа)\s+(?:\d+\s+(?:мешк[ао]в?|штук|листов|кубов)\s+)?(.+?)(?:\s+за|\s+на|$)", text)
    product = prod_match.group(1) if prod_match else "товар"

    return Sale(
        tx_id=uuid.uuid4().hex[:8],
        occurred_at=datetime.now(),
        amount_kopecks=amount_rub * 100,
        lines=[GoodsLine(name=product.strip(), qty=qty, unit=unit_canon)],
        location=location,
        payment=PaymentMethod.CASH if "наличн" in text_lower else PaymentMethod.UNKNOWN,
        confidence=Confidence(text=0.7, amount=0.8, quantity=0.7),
        raw_text=text,
    )


async def parse_text(text: str, use_mock_llm: bool = False) -> None:
    """Полный pipeline: LLM → DialogEngine → отчёт."""
    print(f"\n📝 Вход: {text!r}")

    parsed = None
    if use_mock_llm:
        parsed = _mock_parse(text)
        if parsed is None:
            print("⚠️  Мок-парсер не справился — попробуй фразу типа 'продал 30 мешков цемента за 18 тысяч наличными на Зинино'")
            return
        print(f"🧪 Мок-парсер: {type(parsed).__name__}")
    elif settings.gigachat_credentials:
        try:
            from src.llm import get_parser
            parser = get_parser()
            print(f"🤖 LLM backend: {parser.name}")
            parsed = await parser.parse(text)
            print(f"✅ Распарсено: {type(parsed).__name__}")
        except Exception as e:
            print(f"⚠️  Парсер упал: {e}")
            return
    else:
        print("⚠️  GIGACHAT_CREDENTIALS не задан — используй --mock-llm для демо или заполни .env.")
        return

    # Канонизация
    engine, catalog = _make_engine_with_evgeny_catalog()
    if hasattr(parsed, "lines") and parsed.lines and catalog:
        print(f"\n📚 Канонизация ({catalog.size()} известных SKU):")
        for line in parsed.lines:
            unit_canon = canonicalize_unit(line.unit) or line.unit
            print(f"  {line.name!r} × {line.qty} {line.unit!r}")
            print(f"    единица канон: {unit_canon}")
            matches = catalog.lookup(line.name, top_k=3, min_score=0.5)
            if matches:
                for m in matches:
                    print(f"    fuzzy: {m.score:.2f}  {m.canon!r}")
            else:
                print("    (нет похожих — новый товар?)")

    if hasattr(parsed, "location") and parsed.location:
        print(f"\n📍 Точка: {parsed.location.value}")

    # Решение DialogEngine
    decision = engine.decide(parsed)
    print(f"\n🎯 Решение: {decision.step.value}")
    if decision.message:
        print(f"   Сообщение: {decision.message}")
    if decision.semantic_hash:
        print(f"   Хэш для дедупа: {decision.semantic_hash}")

    # Демо записи в мок-Sheets
    if decision.step == DialogStep.WRITE and isinstance(parsed, Sale):
        print(f"\n💾 Демо записи в in-memory мок-таблицу:")
        from tests.conftest import FakeSpreadsheet
        from src.sheets.schema import SHEET_GOODS, SHEET_MONEY, MONEY_HEADERS, GOODS_HEADERS
        from src.sheets.writer import write_sale

        ss = FakeSpreadsheet()
        ws_m = ss.add_worksheet(SHEET_MONEY)
        ws_m.append_row(MONEY_HEADERS)
        ws_g = ss.add_worksheet(SHEET_GOODS)
        ws_g.append_row(GOODS_HEADERS)

        result = write_sale(ss, parsed)
        print(f"   tx_id={result.tx_id}, summary={result.summary}")
        print(f"   Строка в Деньгах: {ws_m.rows[1]}")
        print(f"   Строка в Товарах: {ws_g.rows[1]}")

    print()


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="CLI-runner для max-money-bot без MAX")
    parser.add_argument("text", nargs="?", help="Текст для парсинга")
    parser.add_argument("--interactive", "-i", action="store_true", help="Интерактивный режим")
    parser.add_argument("--mock-llm", action="store_true", help="Использовать мок-парсер вместо GigaChat (для демо)")
    args = parser.parse_args()

    if args.interactive:
        print("Интерактивный режим. Пиши фразы, Ctrl+D или 'выход' для завершения.")
        while True:
            try:
                text = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text.lower() in ("выход", "exit", "quit"):
                break
            if not text:
                continue
            asyncio.run(parse_text(text, use_mock_llm=args.mock_llm))
    elif args.text:
        asyncio.run(parse_text(args.text, use_mock_llm=args.mock_llm))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
