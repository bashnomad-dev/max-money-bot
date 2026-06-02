"""CLI runner: текст с консоли → парсер → решение DialogEngine → отчёт.

Использование:
    python -m scripts.cli "Продал 30 мешков цемента за 18 тысяч наличными на Зинино"
    python -m scripts.cli --interactive

Запись в Sheets и реальные вызовы GigaChat выполняются только если
переменные среды настроены. Иначе показывается mock-разбор для отладки.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
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

log = logging.getLogger("cli")


def _make_engine_with_evgeny_catalog() -> DialogEngine:
    """Загружает прайс Евгения для канонизации без обращения к Sheets."""
    catalog = ProductCatalog.from_import_json(
        Path("docs/intake/evgeny/price-normalized.json")
    )
    return DialogEngine(
        known_product_canons={e.canon.lower() for e in catalog._entries},
        known_locations={"магазин зинино", "магазин кармалы"},
    ), catalog


async def parse_text(text: str) -> None:
    """Полный pipeline: GigaChat → ParsedCommand → DialogEngine.decide() → отчёт."""
    print(f"\n📝 Вход: {text!r}")

    # Шаг 1: попытка парсить через GigaChat (если ключ есть)
    parsed = None
    if settings.gigachat_credentials:
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
        print("⚠️  GIGACHAT_CREDENTIALS не задан — пропускаю реальный парсер.")
        print("    (Чтобы запустить, заполни .env GIGACHAT_CREDENTIALS и повтори.)")
        return

    # Шаг 2: показать canonicalize hints
    if hasattr(parsed, "lines") and parsed.lines:
        engine, catalog = _make_engine_with_evgeny_catalog()
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
    else:
        engine = DialogEngine()

    if hasattr(parsed, "location") and parsed.location:
        print(f"\n📍 Точка: {parsed.location.value}")

    # Шаг 3: решение DialogEngine
    decision = engine.decide(parsed)
    print(f"\n🎯 Решение: {decision.step.value}")
    if decision.message:
        print(f"   Сообщение: {decision.message}")
    if decision.semantic_hash:
        print(f"   Хэш для дедупа: {decision.semantic_hash}")

    print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="CLI-runner для max-money-bot без MAX")
    parser.add_argument("text", nargs="?", help="Текст для парсинга")
    parser.add_argument("--interactive", "-i", action="store_true", help="Интерактивный режим")
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
            asyncio.run(parse_text(text))
    elif args.text:
        asyncio.run(parse_text(args.text))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
