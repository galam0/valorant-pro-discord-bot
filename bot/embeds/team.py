"""팀 정보 Embed."""

from __future__ import annotations

import discord

from bot.database.repository import TeamDetail
from bot.embeds.common import COLOR_MAIN, clip, ts
from bot.embeds.match import _perspective, recent_line
from bot.utils.korean import STAFF_ROLES, country_ko, flag_emoji, role_ko


def team_embed(detail: TeamDetail) -> discord.Embed:
    team = detail.team
    country = country_ko(team.country_code, team.country_name) or "국가 정보 없음"
    latest_event = next((m.tournament_name for m in detail.upcoming + detail.recent if m.tournament_name), None)

    desc = [f"{flag_emoji(team.country_code)} {country}" + (f"  ·  🏆 {latest_event}" if latest_event else "")]

    live = next((m for m in detail.upcoming if m.status == "live"), None)
    nxt = next((m for m in detail.upcoming if m.status == "upcoming"), None)
    if live:
        _, opp, my, op = _perspective(live, team.id)
        desc.append(f"\n🔴 **LIVE**  vs **{opp}**  `{my or 0} : {op or 0}`")
    elif nxt:
        _, opp, _, _ = _perspective(nxt, team.id)
        desc.append(f"\n📅 다음 경기  vs **{opp}** · {ts(nxt.scheduled_at, 'R')}")

    embed = discord.Embed(title=team.name, url=team.vlr_url, description="\n".join(desc), color=COLOR_MAIN)
    if team.logo_url:
        embed.set_thumbnail(url=team.logo_url)

    # --- 로스터 (선수 / 스태프 나란히) ---
    players, staff = [], []
    for m in detail.members:
        if m.role in STAFF_ROLES:
            staff.append(f"{m.name} · {role_ko(m.role)}")
        else:
            mark = " ⭐" if m.is_captain else ""
            extra = f" ({role_ko(m.role)})" if m.role != "player" else ""
            players.append(f"{m.name}{mark}{extra}")
    embed.add_field(name="👥 선수", value=clip("\n".join(players) or "정보 없음"), inline=True)
    embed.add_field(name="🎧 스태프", value=clip("\n".join(staff) or "정보 없음"), inline=True)

    # --- 최근 전적 ---
    if detail.recent:
        wins = losses = 0
        for m in detail.recent:
            _, _, my, op = _perspective(m, team.id)
            if my is not None and op is not None:
                wins += my > op
                losses += my < op
        embed.add_field(
            name=f"📊 최근 {len(detail.recent)}경기  {wins}승 {losses}패",
            value=clip("\n".join(recent_line(m, team.id) for m in detail.recent)),
            inline=False,
        )
    else:
        embed.add_field(name="📊 최근 전적", value="기록 없음", inline=False)

    embed.set_footer(text="아래 메뉴에서 경기를 고르면 맵별 기록을 볼 수 있어요 · VLR.gg")
    if team.last_scraped_at:
        embed.timestamp = team.last_scraped_at
    return embed
