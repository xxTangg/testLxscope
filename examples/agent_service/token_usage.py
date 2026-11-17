# -*- coding: utf-8 -*-
"""Summarize token usage from saved session messages."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from agentscope.app.storage import RedisStorage


class _Tokens(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class _MessageUsage(BaseModel):
    created_at: datetime
    usage: _Tokens | None = None


class UsageTotals(_Tokens):
    total_tokens: int = 0
    message_count: int = 0
    session_count: int = 0

    def add(self, tokens: _Tokens) -> None:
        self.input_tokens += tokens.input_tokens
        self.output_tokens += tokens.output_tokens
        self.cache_input_tokens += tokens.cache_input_tokens
        self.cache_creation_input_tokens += tokens.cache_creation_input_tokens
        self.total_tokens += tokens.input_tokens + tokens.output_tokens
        self.message_count += 1


class DailyTokenUsage(UsageTotals):
    date: str


class TokenUsage(UsageTotals):
    daily: list[DailyTokenUsage] = Field(default_factory=list)


async def get_token_usage(
    storage: RedisStorage,
    user_id: str,
    *,
    days: int | None = None,
) -> TokenUsage:
    """Read saved usage, optionally limited to recent calendar days."""
    client = storage.get_client()
    today = date.today()
    first_day = today - timedelta(days=days - 1) if days else None
    result = TokenUsage()
    daily: dict[date, DailyTokenUsage] = {}
    seen_keys = set()
    pattern = storage.key_config.messages.format(user_id=user_id, session_id="*")
    async for key in client.scan_iter(match=pattern, count=100):
        if key in seen_keys:
            continue
        seen_keys.add(key)
        session_days = set()
        for raw in await client.lrange(key, 0, -1):
            try:
                message = _MessageUsage.model_validate_json(raw)
            except ValidationError:
                continue
            if message.usage is None:
                continue
            day = message.created_at.date()
            if first_day is not None and not first_day <= day <= today:
                continue
            result.add(message.usage)
            if day not in daily:
                daily[day] = DailyTokenUsage(date=day.isoformat())
            daily[day].add(message.usage)
            session_days.add(day)
        for day in session_days:
            daily[day].session_count += 1
        if days is None or session_days:
            result.session_count += 1

    result.daily = [daily[day] for day in sorted(daily, reverse=True)]
    return result
