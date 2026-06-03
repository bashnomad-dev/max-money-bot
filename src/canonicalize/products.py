"""Канонизация товаров — fuzzy match по справочнику из прайса Евгения.

Стратегия (SPEC §7.2):
  - similarity ≥ 0.90 → автоподстановка канонического имени.
  - 0.70 – 0.90 → карточка с 1-3 кандидатами на выбор.
  - < 0.70 → карточка «новый товар?».

Backend: rapidfuzz (быстрый, скоринг 0..100).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# rapidfuzz импортируется лениво (в lookup) чтобы юнит-тесты домена не требовали его


@dataclass(frozen=True)
class ProductMatch:
    canon: str
    score: float  # 0..1


@dataclass
class CatalogEntry:
    canon: str
    default_unit: str | None = None
    retail_price_kopecks: int | None = None
    aliases: tuple[str, ...] = ()


class ProductCatalog:
    """In-memory справочник товаров для fuzzy-канонизации.

    Загружается один раз при старте бота из products_cache (SQLite) или
    из products-import.json (первичный setup).
    """

    def __init__(self, entries: Iterable[CatalogEntry]) -> None:
        self._entries: list[CatalogEntry] = list(entries)
        # Плоский список «канон + алиасы» с указанием на запись
        self._search_index: list[tuple[str, CatalogEntry]] = []
        for e in self._entries:
            self._search_index.append((e.canon.lower(), e))
            for alias in e.aliases:
                self._search_index.append((alias.lower(), e))

    @classmethod
    def from_import_json(cls, path: Path) -> "ProductCatalog":
        """Загрузка из docs/intake/evgeny/price-normalized.json."""
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = []
        seen_canons: set[str] = set()
        for p in data["products"]:
            canon = p["name"]
            if canon in seen_canons:
                continue
            seen_canons.add(canon)
            entries.append(
                CatalogEntry(
                    canon=canon,
                    default_unit=p.get("unit"),
                    retail_price_kopecks=int(round(p["price_rub"] * 100)) if p.get("price_rub") else None,
                )
            )
        return cls(entries)

    def size(self) -> int:
        return len(self._entries)

    def add(self, canon: str, default_unit: str | None = None) -> bool:
        """Добавить новый канон в каталог in-memory. True если новый, False если был.

        Сравнение case-insensitive по `canon`. Не персистится автоматически —
        для записи в Sheets «Товары» см. src.sheets.setup.append_product.
        """
        if not canon:
            return False
        canon_lower = canon.lower()
        for e in self._entries:
            if e.canon.lower() == canon_lower:
                return False
        entry = CatalogEntry(canon=canon, default_unit=default_unit)
        self._entries.append(entry)
        self._search_index.append((canon_lower, entry))
        return True

    def lookup(self, query: str, top_k: int = 3, min_score: float = 0.5) -> list[ProductMatch]:
        """Найти топ-K похожих канонических имён. Score 0..1."""
        if not query or not self._entries:
            return []
        from rapidfuzz import fuzz, process  # type: ignore

        candidates = process.extract(
            query.lower(),
            [s for s, _ in self._search_index],
            scorer=fuzz.WRatio,
            limit=top_k * 3,  # с запасом, потом дедуп по канону
        )
        # candidates: list of (matched_string, score_0_100, index_in_search_index)
        seen_canons: set[str] = set()
        results: list[ProductMatch] = []
        for _matched, score, idx in candidates:
            entry = self._search_index[idx][1]
            if entry.canon in seen_canons:
                continue
            score_norm = score / 100.0
            if score_norm < min_score:
                continue
            seen_canons.add(entry.canon)
            results.append(ProductMatch(canon=entry.canon, score=score_norm))
            if len(results) >= top_k:
                break
        return results

    def best_match(self, query: str) -> ProductMatch | None:
        matches = self.lookup(query, top_k=1, min_score=0.5)
        return matches[0] if matches else None
