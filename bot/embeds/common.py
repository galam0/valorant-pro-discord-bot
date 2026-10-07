"""Embed 공통 요소."""

from __future__ import annotations

from datetime import datetime

import discord

COLOR_MAIN = discord.Color.from_rgb(255, 70, 85)    # VALORANT 레드
COLOR_INFO = discord.Color.from_rgb(88, 101, 242)
COLOR_WARN = discord.Color.from_rgb(250, 166, 26)
COLOR_OK = discord.Color.from_rgb(67, 181, 129)

FIELD_LIMIT = 1024


def clip(text: str, limit: int = FIELD_LIMIT) -> str:
    """Embed 필드 길이 제한(1024자)에 맞춰 줄 단위로 자른다."""
    if len(text) <= limit:
        return text or "​"
    lines, total = [], 0
    for line in text.split("\n"):
        if total + len(line) + 1 > limit - 2:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) + "\n…"


def ts(dt: datetime | None, style: str = "f") -> str:
    """Discord 타임스탬프. 보는 사람의 시간대로 자동 표시된다. (f: 날짜+시각, R: 상대시간, d: 날짜)"""
    if dt is None:
        return "시간 미정"
    return f"<t:{int(dt.timestamp())}:{style}>"


def error_embed(message: str) -> discord.Embed:
    return discord.Embed(description=f"⚠️ {message}", color=COLOR_WARN)


def info_embed(message: str) -> discord.Embed:
    return discord.Embed(description=message, color=COLOR_INFO)
