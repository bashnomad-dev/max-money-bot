"""GigaChat реализация LLMParser. Основной бэкенд (российский стек).

Документация GigaChat: https://developers.sber.ru/docs/ru/gigachat/api/overview
Python SDK: pip install gigachat
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from src.llm.tools import tool_names as _tool_names

from src.config.settings import settings
from src.domain.operation import ParsedCommand
from src.llm.base import LLMParseError, LLMTransportError
from src.llm.prompts import SYSTEM_PROMPT_RU
from src.llm.tools import TOOLS
from src.llm.tool_to_domain import build_command_from_tool_call

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class GigaChatParser:
    """LLMParser через GigaChat function calling."""

    name = "gigachat"

    def __init__(self) -> None:
        if not settings.gigachat_credentials:
            raise LLMTransportError("GIGACHAT_CREDENTIALS не задан в .env")
        # Ленивый импорт чтобы тесты домена не требовали установленного gigachat
        from gigachat import GigaChat  # type: ignore

        self._client = GigaChat(
            credentials=settings.gigachat_credentials,
            scope=settings.gigachat_scope,
            model=settings.gigachat_model,
            verify_ssl_certs=settings.gigachat_verify_ssl,
            timeout=settings.gigachat_timeout_sec,
        )

    async def parse(self, text: str) -> ParsedCommand:
        """Прогон одного текстового сообщения через GigaChat function calling."""
        from gigachat.models import (  # type: ignore
            Chat,
            Function,
            Messages,
            MessagesRole,
        )

        # Преобразуем наши TOOLS в формат GigaChat Function
        functions = [
            Function(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
            )
            for t in TOOLS
        ]

        chat_request = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=SYSTEM_PROMPT_RU),
                Messages(role=MessagesRole.USER, content=text),
            ],
            functions=functions,
            function_call="auto",
            temperature=0.0,
        )

        # Простой backoff на 429 (PERS-тариф лимитит ~1 RPS).
        # Делаем до 3 попыток с экспоненциальной паузой: 2с → 4с → 8с.
        response = None
        for attempt in range(3):
            try:
                response = self._client.chat(chat_request)
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                is_429 = " 429 " in msg or "Too Many Requests" in msg or "RateLimit" in type(exc).__name__
                if is_429 and attempt < 2:
                    pause = 2 ** (attempt + 1)
                    log.warning("GigaChat 429, ждём %dс (попытка %d/3)", pause, attempt + 1)
                    await asyncio.sleep(pause)
                    continue
                log.exception("GigaChat transport error")
                raise LLMTransportError(msg) from exc
        if response is None:
            raise LLMTransportError("GigaChat исчерпал попытки ретрая")

        choice = response.choices[0]
        function_call = getattr(choice.message, "function_call", None)
        tool_name: str | None = None
        tool_args: dict | None = None

        if function_call is not None:
            tool_name = function_call.name
            args = function_call.arguments
            try:
                tool_args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError as exc:
                raise LLMParseError(f"GigaChat вернул невалидный JSON: {exc}") from exc
        else:
            # Fallback: GigaChat иногда возвращает псевдо-function-call в content
            # вида "tool_name\n{...}", где строковые литералы обёрнуты в
            # <|superquote|>…<|superquote|>. Достаём имя и JSON-тело.
            tool_name, tool_args = _parse_pseudo_function_call(choice.message.content or "")
            if tool_name is None:
                raise LLMParseError(
                    f"GigaChat не вызвал function. Ответ: {(choice.message.content or '')[:200]!r}"
                )
            log.warning("GigaChat вернул tool_call в content (fallback-парсинг сработал): %s", tool_name)

        tx_id = uuid.uuid4().hex[:8]
        occurred_at = datetime.now()

        try:
            return build_command_from_tool_call(
                tool_name=tool_name,
                tool_args=tool_args or {},
                raw_text=text,
                tx_id=tx_id,
                occurred_at=occurred_at,
            )
        except (ValueError, KeyError) as exc:
            raise LLMParseError(
                f"GigaChat вызвал {tool_name} с невалидными аргументами: {exc}"
            ) from exc


_SUPERQUOTE = "<|superquote|>"


def _parse_pseudo_function_call(content: str) -> tuple[str | None, dict | None]:
    """Fallback-парсер: контент вида "<tool_name>\n{json}".

    GigaChat-Max иногда «эмулирует» function call в content. Строковые литералы
    оборачиваются собственным маркером <|superquote|>…<|superquote|> вместо
    обычных двойных кавычек — заменяем на ", после чего пытаемся распарсить JSON.
    """
    if not content:
        return None, None
    # Заменяем суперквоты на обычные кавычки
    cleaned = content.replace(_SUPERQUOTE, '"')
    # Первая строка — имя tool, остальное — JSON-тело
    lines = cleaned.strip().split("\n", 1)
    if len(lines) < 1:
        return None, None
    candidate_name = lines[0].strip().strip('"').strip()
    if candidate_name not in _tool_names():
        return None, None
    body = lines[1].strip() if len(lines) >= 2 else "{}"
    # Иногда тело без обёртки {} — пытаемся обернуть
    if not body.startswith("{"):
        body = "{" + body + "}"
    try:
        args = json.loads(body)
    except json.JSONDecodeError:
        # Грубый ремонт: убрать висящие запятые перед }
        body2 = re.sub(r",\s*}", "}", body)
        try:
            args = json.loads(body2)
        except json.JSONDecodeError:
            return None, None
    return candidate_name, args
