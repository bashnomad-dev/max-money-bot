"""GigaChat реализация LLMParser. Основной бэкенд (российский стек).

Документация GigaChat: https://developers.sber.ru/docs/ru/gigachat/api/overview
Python SDK: pip install gigachat
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

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

        try:
            # GigaChat SDK имеет sync API; для async обернём в run_in_executor при необходимости
            response = self._client.chat(chat_request)
        except Exception as exc:  # noqa: BLE001
            log.exception("GigaChat transport error")
            raise LLMTransportError(str(exc)) from exc

        choice = response.choices[0]
        function_call = getattr(choice.message, "function_call", None)
        if function_call is None:
            # Модель ответила свободным текстом — нарушение протокола
            raise LLMParseError(
                f"GigaChat не вызвал function. Ответ: {choice.message.content[:200]!r}"
            )

        tool_name = function_call.name
        try:
            tool_args = function_call.arguments
            if isinstance(tool_args, str):
                tool_args = json.loads(tool_args)
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"GigaChat вернул невалидный JSON в arguments: {exc}") from exc

        tx_id = uuid.uuid4().hex[:8]
        occurred_at = datetime.now()

        try:
            return build_command_from_tool_call(
                tool_name=tool_name,
                tool_args=tool_args,
                raw_text=text,
                tx_id=tx_id,
                occurred_at=occurred_at,
            )
        except (ValueError, KeyError) as exc:
            raise LLMParseError(
                f"GigaChat вызвал {tool_name} с невалидными аргументами: {exc}"
            ) from exc
