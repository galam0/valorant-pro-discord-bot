"""팀 정보 Embed (Phase 5에서 버튼·페이지 등 UI를 더 다듬는다)."""

from __future__ import annotations

import discord

from bot.database.repository import TeamDetail
from bot.embeds.common import COLOR_MAIN, clip
from bot.embeds.match import match_line_for_team
from bot.utils.korean import STAFF_ROLES, country_ko, flag_emoji, role_ko


def team_embed(detail: TeamDetail) -> discord.Embed:
    team = detail.team
    flag = flag_emoji(team.country_code)
    country = country_ko(team.country_code, team.country_name) or "국가 정보 없음"

    embed = discord.Embed(
        title=team.name,
        url=team.vlr_url,
        description=f"{flag} {country}" + (f" · `{team.tag}`" if team.tag and team.tag != team.name else ""),
        color=COLOR_MAIN,
    )
    if team.logo_url:
        embed.set_thumbnail(url=team.logo_url)

    # --- 로스터 ---
    players, staff = [], []
    for m in detail.members:
        real = f" · {m.real_name}" if m.real_name else ""
        captain = " ⭐" if m.is_captain else ""
        if m.role in STAFF_ROLES:
            staff.append(f"{flag_emoji(m.country_code)} **{m.name}** — {role_ko(m.role)}")
        else:
            tag = f" `{role_ko(m.role)}`" if m.role != "player" else ""
            players.append(f"{flag_emoji(m.country_code)} **{m.name}**{captain}{tag}{real}")

    embed.add_field(name="👥 현재 로스터", value=clip("\n".join(players) or "정보 없음"), inline=False)
    if staff:
        embed.add_field(name="🎧 코칭 스태프", value=clip("\n".join(staff)), inline=False)

    # --- 경기 ---
    if detail.upcoming:
        embed.add_field(
            name="📅 예정 경기",
            value=clip("\n".join(match_line_for_team(m, team.id) for m in detail.upcoming[:3])),
            inline=False,
        )
    embed.add_field(
        name="📊 최근 경기",
        value=clip("\n".join(match_line_for_team(m, team.id) for m in detail.recent) or "기록 없음"),
        inline=False,
    )

    latest = next((m.tournament_name for m in detail.upcoming + detail.recent if m.tournament_name), None)
    if latest:
        embed.add_field(name="🏆 최근 대회", value=latest, inline=False)

    links = [f"[VLR.gg 팀 페이지]({team.vlr_url})"] if team.vlr_url else []
    if links:
        embed.add_field(name="🔗 링크", value=" · ".join(links), inline=False)

    embed.set_footer(text="출처: VLR.gg · 마지막 업데이트")
    if team.last_scraped_at:
        embed.timestamp = team.last_scraped_at
    return embed
