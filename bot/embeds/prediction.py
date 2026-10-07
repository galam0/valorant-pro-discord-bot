"""VP·예측 화면용 Embed."""

from __future__ import annotations

import discord

from bot.embeds.common import COLOR_INFO, COLOR_MAIN, COLOR_OK, COLOR_WARN, ts
from bot.services import odds_model as om
from bot.services.economy_service import fmt

KIND_KO = {"winner": "승패", "score": "맵 스코어", "mvp": "MVP"}
STATUS_KO = {"open": "⏳ 대기", "won": "✅ 적중", "lost": "❌ 실패", "void": "↩️ 환불", "cancelled": "🚫 취소"}


def wallet_embed(balance: int, rank: int, total: int, *, checked: bool | None = None, got: int = 0) -> discord.Embed:
    embed = discord.Embed(title="💰 내 VP", description=f"**{fmt(balance)}**", color=COLOR_OK)
    embed.add_field(name="서버 순위", value=f"{rank}위 / {total}명" if total else "-", inline=True)
    if checked is True:
        embed.set_footer(text=f"출석 보상 +{got} VP 받았어요!")
    elif checked is False:
        embed.set_footer(text="오늘은 이미 출석했어요. 내일 다시 받을 수 있어요.")
    else:
        embed.set_footer(text="VP는 이 서버에서만 쓰는 가상 재화예요. 현금 가치는 없어요.")
    return embed


def leaderboard_embed(rows: list[tuple[int, int]], guild_name: str) -> discord.Embed:
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else f'`{i + 1}`'} <@{uid}> — {fmt(bal)}" for i, (uid, bal) in enumerate(rows)]
    return discord.Embed(title=f"🏆 {guild_name} VP 랭킹", description="\n".join(lines) or "아직 아무도 없어요. `/출석`으로 시작해보세요!",
                         color=COLOR_MAIN)


def market_embed(m, mine: list, state: str) -> discord.Embed:
    when = ts(m.scheduled_at, "f") + " (" + ts(m.scheduled_at, "R") + ")"
    embed = discord.Embed(title=f"🎯 {m.team1} vs {m.team2}", color=COLOR_MAIN)
    embed.description = f"{m.tournament or ''}\n시작: {when}"
    src = "VLR.gg 배당 기준" if m.odds.from_vlr else "기본 배율 (VLR 배당 없음)"
    embed.add_field(name=f"승패 · {src}",
                    value=f"**{m.team1}** ×{m.odds.winner[0]:.2f}\n**{m.team2}** ×{m.odds.winner[1]:.2f}", inline=False)
    if m.score_options():
        embed.add_field(name="맵 스코어", value=" · ".join(f"`{s.replace('-', ':')}` ×{x:.2f}" for s, x in m.score_options()), inline=False)
    else:
        embed.add_field(name="맵 스코어", value="단판 경기라 예측할 수 없어요.", inline=False)
    embed.add_field(name="MVP", value="선수 고르기 · 배율은 선수 소속 팀의 승리 확률로 정해져요 (×3~)", inline=False)
    if mine:
        embed.add_field(name="내 예측", value=prediction_lines(mine), inline=False)
    if state == "open":
        embed.set_footer(text=f"{om.MIN_STAKE:,}~{om.MAX_STAKE:,} VP · 시작 {om.LOCK_MINUTES}분 전까지 걸 수 있고, 그 전엔 취소 가능해요")
    else:
        embed.colour = COLOR_WARN
        embed.add_field(name="⛔ 마감", value=("이미 경기가 시작되었어요." if state == "started" else "예측이 마감되었어요."), inline=False)
    return embed


def prediction_lines(preds: list) -> str:
    out = []
    for p in preds:
        extra = ""
        if p.status == "won":
            extra = f" → +{p.payout:,}"
        elif p.status == "void":
            extra = " → 환불"
        out.append(f"{STATUS_KO.get(p.status, p.status)} **{KIND_KO.get(p.kind, p.kind)}** {p.pick_label} "
                   f"· {p.stake:,} VP ×{p.odds:.2f}{extra}")
    return "\n".join(out)


def my_predictions_embed(preds: list) -> discord.Embed:
    embed = discord.Embed(title="📋 내 예측", color=COLOR_INFO)
    if not preds:
        embed.description = "아직 예측이 없어요. `/예측`으로 시작해보세요!"
        return embed
    lines = []
    for p in preds:
        m = p.match
        lines.append(f"**{m.team1_name} vs {m.team2_name}**\n{prediction_lines([p])}")
    embed.description = "\n\n".join(lines)[:4000]
    return embed
