"""OpenRouter реализация LLMParser.

OpenRouter — единый OpenAI-совместимый API к Claude / GPT / Gemini / Llama / др.
Используем openai SDK с base_url=openrouter — поддержка function calling
работает out-of-the-box у Claude и GPT (а у моделей похуже её просто не будет).

По умолчанию модель: anthropic/claude-haiku-4.5 — лучшее соотношение
качества function calling к цене из доступных в OpenRouter.

Документация: https://openrouter.ai/docs
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from src.config.settings import settings
from src.domain.operation import ParsedCommand
from src.llm.base import LLMParseError, LLMTransportError
from src.llm.prompts import SYSTEM_PROMPT_RU
from src.llm.tools import TOOLS
from src.llm.tool_to_domain import build_command_from_tool_call

log = logging.getLogger(__name__)


class OpenRouterParser:
    """LLMParser через OpenRouter (OpenAI-совместимый endpoint)."""

    name = "openrouter"

    def __init__(self) -> None:
        if not settings.openrouter_api_key:
            raise LLMTransportError("OPENROUTER_API_KEY не задан в .env")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise LLMTransportError(
                "Не установлен пакет openai. pip install openai"
            ) from e
        self._client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout_sec,
            default_headers={
                # OpenRouter рекомендует, не обязательно
                "HTTP-Referer": "https://github.com/bashnomad-dev/max-money-bot",
                "X-Title": "max-money-bot",
            },
        )

    async def parse(self, text: str) -> ParsedCommand:
        """Прогон одного текста через OpenRouter с function calling."""
        # Преобразуем TOOLS (наш формат) → OpenAI-формат tools
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in TOOLS
        ]

        # OpenAI SDK синхронный — оборачиваем в run_in_executor чтобы не блокировать loop
        loop = asyncio.get_running_loop()

        for attempt in range(3):
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self._client.chat.completions.create(
                        model=settings.openrouter_model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT_RU},
                            {"role": "user", "content": text},
                        ],
                        tools=openai_tools,
                        tool_choice="required",  # модель обязана вызвать tool
                        temperature=0.0,
                    ),
                )
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                # Транзиентные ошибки сети / 429 / 5xx → backoff
                is_retriable = (
                    "429" in msg
                    or "rate" in msg.lower()
                    or "timeout" in msg.lower()
                    or " 5" in msg  # 500/502/503/504
                )
                if is_retriable and attempt < 2:
                    pause = 2 ** (attempt + 1)
                    log.warning("OpenRouter transient error (%s), ждём %dс (попытка %d/3)", msg[:80], pause, attempt + 1)
                    await asyncio.sleep(pause)
                    continue
                log.exception("OpenRouter transport error")
                raise LLMTransportError(msg) from exc
        else:
            raise LLMTransportError("OpenRouter исчерпал попытки ретрая")

        choice = response.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        if not tool_calls:
            content = (choice.message.content or "")[:200]
            raise LLMParseError(f"OpenRouter не вызвал function. Ответ: {content!r}")

        call = tool_calls[0]
        tool_name = call.function.name
        try:
            tool_args = json.loads(call.function.arguments)
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"OpenRouter вернул невалидный JSON в arguments: {exc}") from exc

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
                f"OpenRouter вызвал {tool_name} с невалидными аргументами: {exc}"
            ) from exc
