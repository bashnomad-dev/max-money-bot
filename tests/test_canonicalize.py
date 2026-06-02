"""Тесты канонизации (единицы, точки, товары по реальному прайсу)."""
from pathlib import Path

import pytest

from src.canonicalize import (
    ProductCatalog,
    canonicalize_location,
    canonicalize_unit,
)
from src.domain.operation import Location


class TestCanonicalizeUnit:
    @pytest.mark.parametrize("input_unit,expected", [
        ("мешков", "меш."),
        ("мешок", "меш."),
        ("меш.", "меш."),
        ("штук", "шт."),
        ("шт", "шт."),
        ("кубов", "м3"),
        ("куб", "м3"),
        ("м³", "м3"),
        ("квадратов", "м2"),
        ("м²", "м2"),
        ("кв.м", "m2".replace("m", "м")),
        ("погонных метров", "м.п."),
        ("листов", "шт."),
        ("литры", "л."),
        ("килограммов", "кг"),
    ])
    def test_known(self, input_unit, expected):
        assert canonicalize_unit(input_unit) == expected

    def test_unknown_returns_none(self):
        assert canonicalize_unit("какая-то_единица") is None

    def test_empty(self):
        assert canonicalize_unit("") is None


class TestCanonicalizeLocation:
    @pytest.mark.parametrize("input_text,expected", [
        ("Зинино", Location.ZININO),
        ("магазин Зинино", Location.ZININO),
        ("на Зинино", Location.ZININO),
        ("зенино", Location.ZININO),
        ("Кармалы", Location.KARMALY),
        ("на Кармалы", Location.KARMALY),
        ("кормал", Location.KARMALY),
    ])
    def test_known(self, input_text, expected):
        assert canonicalize_location(input_text) == expected

    def test_unknown(self):
        assert canonicalize_location("Москва") is None
        assert canonicalize_location("") is None
        assert canonicalize_location(None) is None


@pytest.fixture(scope="module")
def evgeny_catalog() -> ProductCatalog:
    """Загружаем прайс Евгения один раз на модуль (4883 SKU)."""
    return ProductCatalog.from_import_json(Path("docs/intake/evgeny/price-normalized.json"))


class TestProductCatalog:
    def test_loads_4883_canons(self, evgeny_catalog):
        assert evgeny_catalog.size() == 4883

    def test_lookup_cement_finds_sterlitamak(self, evgeny_catalog):
        matches = evgeny_catalog.lookup("цемент стерлитамак", top_k=3)
        assert len(matches) > 0
        top_canon = matches[0].canon.lower()
        assert "цемент" in top_canon and "стерлитамак" in top_canon
        assert matches[0].score >= 0.85

    def test_lookup_unknown_returns_low_or_none(self, evgeny_catalog):
        # Заведомо несуществующий товар (даже отдельные слоги не должны давать совпадений)
        matches = evgeny_catalog.lookup("zzzqqqxxxyyy_random_garbage_string_xyz_99999", top_k=3)
        # Либо пусто, либо score ниже порога авто-канонизации (0.9)
        for m in matches:
            assert m.score < 0.7

    def test_best_match_works(self, evgeny_catalog):
        m = evgeny_catalog.best_match("имитация бруса")
        assert m is not None
        assert m.score >= 0.8
