"""주식 알림·내역 Embed."""

from __future__ import annotations

import discord

from bot.embeds.common import COLOR_INFO, COLOR_MAIN, ts
from bot.services import stock_model as sm


def surge_embed(surges: list[tuple[str, int, int, float]]) -> discord.Embed:
    """주가 급등락 알림. 한국식 색/기호: 오르면 ▲, 내리면 ▼."""
    lines = []
    for sym, old, new, pct in surges:
        arrow = "🔺" if pct > 0 else "🔻"
        lines.append(f"{arrow} **{sm.BY_SYMBOL[sym].name}** {old:,} → {new:,} VP ({pct:+.1f}%)")
    e = discord.Embed(title="📢 주가 급등락", description="\n".join(lines), color=COLOR_MAIN if surges and surges[0][3] > 0 else COLOR_INFO)
    e.set_footer(text="`/주식`으로 시세를 확인하세요")
    return e


def history_embed(rows: list, name: str) -> discord.Embed:
    e = discord.Embed(title=f"🧾 {name} 님의 최근 주식 거래", color=COLOR_INFO)
    if not rows:
        e.description = "거래 내역이 없어요. `/매수`로 시작해 보세요!"
        return e
    lines = []
    for kind, stock, qty, price, delta, at in rows:
        mark = "🟥 매수" if kind == "buy" else "🟦 매도"
        lines.append(f"{mark} **{stock}** {qty:,}주 @ {price:,} — {delta:+,} VP · {ts(at, 'R')}")
    e.description = "\n".join(lines)
    e.set_footer(text="VP 변화에는 수수료가 포함돼 있어요")
    return e
