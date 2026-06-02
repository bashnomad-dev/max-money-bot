"""LLM-парсинг: интерфейс + реализации + маппинг tool_call → domain."""
from src.llm.base import LLMError, LLMParseError, LLMParser, LLMTransportError
from src.llm.factory import get_fallback_parser, get_parser
from src.llm.prompts import SYSTEM_PROMPT_RU
from src.llm.tool_to_domain import build_command_from_tool_call
from src.llm.tools import TOOLS, tool_names

__all__ = [
    "LLMError",
    "LLMParseError",
    "LLMParser",
    "LLMTransportError",
    "SYSTEM_PROMPT_RU",
    "TOOLS",
    "build_command_from_tool_call",
    "get_fallback_parser",
    "get_parser",
    "tool_names",
]
