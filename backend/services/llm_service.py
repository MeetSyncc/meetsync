"""
Тонкая обёртка над MeetSync-LLM для использования в aiogram-хендлерах.
"""

from __future__ import annotations

import logging
from typing import Optional

from meetsync_llm import AvailabilityParser, ParsingResult

logger = logging.getLogger(__name__)

# Один экземпляр на процесс (ключ берётся из GROQ_API_KEY / .env)
_parser: Optional[AvailabilityParser] = None


def get_parser() -> AvailabilityParser:
    """Ленивая инициализация парсера. Бросает ValueError, если нет ключа."""
    global _parser
    if _parser is None:
        _parser = AvailabilityParser()
    return _parser


async def parse_user_availability(
    text: str,
    history: list[dict] | None = None,
) -> ParsingResult:
    """
    Разбирает свободный текст пользователя о доступности.

    Возвращает ParsingResult со статусами:
      - success              → показать summary_ru + кнопки подтверждения
      - clarification_needed → задать clarification_message
      - error                → показать error_message;
                              если fallback_to_manual=True — предложить ручной ввод
    """
    parser = get_parser()
    result = await parser.parse_availability(text, history=history)

    logger.info(
        "LLM parse: status=%s, slots=%d, exceptions=%d, fallback=%s",
        result.status,
        len(result.recurring_slots),
        len(result.exceptions),
        result.fallback_to_manual,
    )
    return result
