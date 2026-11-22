
"""Обёртка над MeetSync-LLM (AvailabilityParser)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from meetsync_llm import AvailabilityParser, ParsingResult

logger = logging.getLogger(__name__)

# Загружаем .env из корня MeetSync
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

_parser: Optional[AvailabilityParser] = None


def get_parser() -> AvailabilityParser:
    global _parser

    if _parser is None:
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError(
                f"GROQ_API_KEY не найден. Проверь файл: {PROJECT_ROOT / '.env'}"
            )

        _parser = AvailabilityParser(api_key=api_key)

    return _parser


async def parse_user_availability(
    text: str,
    history: list[dict] | None = None,
) -> ParsingResult:
    parser = get_parser()

    result = await parser.parse_availability(text, history=history)

    logger.info(
        "LLM parse: status=%s, recurring=%d, exceptions=%d, fallback=%s",
        result.status,
        len(result.recurring_slots),
        len(result.exceptions),
        result.fallback_to_manual,
    )

    return result
