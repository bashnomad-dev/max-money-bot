"""Тесты упрощений под тест-неделю Евгения (фикс ДЕМО):
дефолт точки вместо переспроса + отключаемая канонизация товара.
"""
from datetime import datetime

import pytest

from src.config.settings import settings
from src.dialog.engine import DialogEngine, DialogStep
from src.domain.operation import (
    ClarificationNeeded,
    Confidence,
    GoodsLine,
    Location,
    Sale,
)
from src.llm.tool_to_domain import build_command_from_tool_call


def _now():
    return datetime(2026, 6, 11, 12, 0)


def _sale_args(location=None):
    return {
        "amount_rub": 18000,
        "lines": [{"name": "доска 40 на 100", "qty": 5, "unit": "шт."}],
        "location": location,
        "payment": "наличные",
        "text_confidence": 0.95,
        "amount_confidence": 0.95,
        "quantity_confidence": 0.95,
    }


class TestDefaultLocation:
    def test_missing_location_no_default_asks_clarification(self, monkeypatch):
        monkeypatch.setattr(settings, "default_location", "")
        op = build_command_from_tool_call(
            "record_sale", _sale_args(location=None), "test", "tx_1", _now()
        )
        assert isinstance(op, ClarificationNeeded)

    def test_missing_location_uses_default(self, monkeypatch):
        monkeypatch.setattr(settings, "default_location", "Магазин Зинино")
        op = build_command_from_tool_call(
            "record_sale", _sale_args(location=None), "test", "tx_2", _now()
        )
        assert isinstance(op, Sale)
        assert op.location == Location.ZININO

    def test_explicit_location_wins_over_default(self, monkeypatch):
        monkeypatch.setattr(settings, "default_location", "Магазин Зинино")
        op = build_command_from_tool_call(
            "record_sale", _sale_args(location="Магазин Кармалы"), "test", "tx_3", _now()
        )
        assert isinstance(op, Sale)
        assert op.location == Location.KARMALY

    def test_invalid_location_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(settings, "default_location", "Магазин Зинино")
        op = build_command_from_tool_call(
            "record_sale", _sale_args(location="склад3"), "test", "tx_4", _now()
        )
        assert isinstance(op, Sale)
        assert op.location == Location.ZININO


def _sale(name="неведомый товар XYZ"):
    return Sale(
        tx_id="tx",
        occurred_at=_now(),
        amount_kopecks=1_800_000,
        lines=[GoodsLine(name=name, qty=5, unit="шт.")],
        location=Location.ZININO,
        confidence=Confidence(text=0.95, amount=0.95, quantity=0.95),
        raw_text="test",
    )


class TestCanonicalizationToggle:
    def test_unknown_product_canonicalizes_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "enforce_product_canonicalization", True)
        engine = DialogEngine(known_product_canons=set(), known_locations=set())
        res = engine.decide(_sale())
        assert res.step == DialogStep.CANONICALIZE

    def test_unknown_product_writes_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "enforce_product_canonicalization", False)
        engine = DialogEngine(known_product_canons=set(), known_locations=set())
        res = engine.decide(_sale())
        assert res.step == DialogStep.WRITE


class TestSTTFallback:
    """Авто-фолбэк STT: основной упал/пусто → запасной."""

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_fallback_on_error(self):
        from src.stt.factory import FallbackSTTEngine

        class Boom:
            name = "boom"
            async def transcribe(self, p):
                raise RuntimeError("dead")

        class Ok:
            name = "ok"
            async def transcribe(self, p):
                return "распознал"

        eng = FallbackSTTEngine(Boom(), Ok())
        assert eng.name == "boom+ok"
        assert self._run(eng.transcribe(None)) == "распознал"

    def test_fallback_on_empty(self):
        from src.stt.factory import FallbackSTTEngine

        class Empty:
            name = "empty"
            async def transcribe(self, p):
                return ""

        class Ok:
            name = "ok"
            async def transcribe(self, p):
                return "из запасного"

        eng = FallbackSTTEngine(Empty(), Ok())
        assert self._run(eng.transcribe(None)) == "из запасного"

    def test_primary_wins_when_ok(self):
        from src.stt.factory import FallbackSTTEngine

        class Ok1:
            name = "p"
            async def transcribe(self, p):
                return "основной"

        class Ok2:
            name = "f"
            async def transcribe(self, p):
                raise AssertionError("не должны вызывать запасной")

        eng = FallbackSTTEngine(Ok1(), Ok2())
        assert self._run(eng.transcribe(None)) == "основной"
