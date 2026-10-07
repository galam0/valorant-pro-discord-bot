"""경기 표시."""

from __future__ import annotations

import discord

from bot.database.models import Match
from bot.embeds.common import COLOR_MAIN, clip, ts
from bot.utils.korean import stage_ko


def match_line_for_team(match: Match, team_id: int) -> str:
    """특정 팀 관점의 한 줄. 예) 🟢 **승리** T1 2 : 0 FUT Esports · <t:..:d>"""
    is_t1 = match.team2_id != team_id
    me, opp = (match.team1_name, match.team2_name) if is_t1 else (match.team2_name, match.team1_name)
    my_s, op_s = (match.team1_score, match.team2_score) if is_t1 else (match.team2_score, match.team1_score)

    if match.status == "live":
        return f"🔴 **진행 중** {me} vs {opp}"
    if match.status == "upcoming":
        return f"📅 {me} vs {opp} · {ts(match.scheduled_at, 'f')}"

    if my_s is None or op_s is None:
        icon, word = "⚪", "결과"
    elif my_s > op_s:
        icon, word = "🟢", "승리"
    elif my_s < op_s:
        icon, word = "🔴", "패배"
    else:
        icon, word = "⚪", "무승부"
    score = f"{my_s} : {op_s}" if my_s is not None and op_s is not None else "vs"
    return f"{icon} **{word}** {me} {score} {opp} · {ts(match.scheduled_at, 'd')}"


def match_line(match: Match) -> str:
    """중립 관점의 경기 블록 (/경기)."""
    if match.status == "live":
        head = "🔴 **LIVE**"
        score = f"{match.team1_score or 0} : {match.team2_score or 0}"
    elif match.status == "completed":
        head = f"✅ 종료 · {ts(match.scheduled_at, 'd')}"
        score = f"{match.team1_score} : {match.team2_score}"
    else:
        head = f"🕐 {ts(match.scheduled_at, 'f')} ({ts(match.scheduled_at, 'R')})"
        score = "vs"

    event = match.tournament_name or "대회 정보 없음"
    stage = stage_ko(match.stage)
    link = f"[VLR]({match.vlr_url})" if match.vlr_url else ""
    return (
        f"{head}\n"
        f"**{match.team1_name}** {score} **{match.team2_name}**\n"
        f"🏆 {event}{' · ' + stage if stage else ''} {link}"
    )


def matches_embed(title: str, matches: list[Match]) -> discord.Embed:
    embed = discord.Embed(title=title, color=COLOR_MAIN)
    if not matches:
        embed.description = "표시할 경기가 없습니다."
        return embed
    embed.description = clip("\n\n".join(match_line(m) for m in matches), 4000)
    embed.set_footer(text="출처: VLR.gg · 시간은 내 시간대로 표시됩니다")
    return embed
