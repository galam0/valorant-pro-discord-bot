"""/경기, /전적 — DB에 저장된 경기와 경기 상세(맵별 기록)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.autocomplete import team_autocomplete
from bot.database import repository as repo
from bot.database.database import db
from bot.embeds.common import error_embed
from bot.embeds.match import matches_embed
from bot.render.cards import DISPLAY_TZ, build_schedule_card
from bot.services import team_service
from bot.views.match import MatchListView, choices_from, send_match_detail

log = logging.getLogger("valobot.cmd.matches")


DAY_CHOICES = [
    app_commands.Choice(name="어제", value=-1),
    app_commands.Choice(name="오늘", value=0),
    app_commands.Choice(name="내일", value=1),
    app_commands.Choice(name="모레", value=2),
]
_WEEKDAY = "월화수목금토일"


class MatchCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="경기", description="진행 중·예정된 프로 경기를 보여줍니다.")
    @app_commands.describe(팀="특정 팀의 경기만 보기 (선택)")
    @app_commands.autocomplete(팀=team_autocomplete)
    async def matches(self, interaction: discord.Interaction, 팀: str | None = None) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer()

        try:
            if 팀:
                detail, _ = await team_service.get_team(팀)
                if detail is None:
                    await interaction.followup.send(embed=error_embed(f"'{팀}' 팀을 찾을 수 없습니다."))
                    return
                listed = detail.upcoming + detail.recent
                embed = matches_embed(f"🎮 {detail.team.name} 경기", listed)
                choices = choices_from(listed, detail.team.id)
            else:
                async with db.session() as s:
                    listed = await repo.get_upcoming_matches(s, limit=8)
                embed = matches_embed("🎮 진행 중 · 예정 경기", listed)
                if not listed:
                    embed.description = "데이터가 아직 수집되지 않았습니다. (관리자: `/관리 경기갱신`)"
                choices = choices_from(listed)
        except Exception:
            log.exception("경기 조회 실패")
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))
            return

        await interaction.followup.send(embed=embed, view=MatchListView(choices))

    @app_commands.command(name="전적", description="팀의 진행 중이거나 최근 경기의 맵별 기록(K/D/A)을 보여줍니다.")
    @app_commands.describe(팀="팀 이름 또는 별칭 (예: T1, 젠지)")
    @app_commands.autocomplete(팀=team_autocomplete)
    async def record(self, interaction: discord.Interaction, 팀: str) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        try:
            detail, _ = await team_service.get_team(팀)
            if detail is None:
                await interaction.followup.send(embed=error_embed(f"'{팀}' 팀을 찾을 수 없습니다."))
                return
            async with db.session() as s:
                team_matches = await repo.get_team_matches(s, detail.team.id, limit=10)
        except Exception:
            log.exception("전적 조회 실패")
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))
            return

        # 진행 중 경기 → 가장 최근 종료 경기 순으로 보여준다 (예정 경기는 기록이 없으므로 제외)
        played = [m for m in team_matches if m.status in ("live", "completed")]
        if not played:
            await interaction.followup.send(embed=error_embed(f"{detail.team.name}의 경기 기록이 아직 없습니다."))
            return
        target = next((m for m in played if m.status == "live"), played[0])
        await send_match_detail(interaction, target.vlr_id, others=choices_from(played, detail.team.id))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MatchCommands(bot))

    @app_commands.command(name="일정", description="하루치 프로 경기 일정을 한 장의 이미지로 보여줍니다.")
    @app_commands.describe(날짜="보고 싶은 날 (기본: 오늘, 한국 시간 기준)")
    @app_commands.choices(날짜=DAY_CHOICES)
    async def schedule(self, interaction: discord.Interaction, 날짜: app_commands.Choice[int] | None = None) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        offset = 날짜.value if 날짜 else 0
        day = (datetime.now(DISPLAY_TZ) + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with db.session() as s:
                listed = await repo.get_matches_between(s, day, day + timedelta(days=1))
        except Exception:
            log.exception("일정 조회 실패")
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))
            return

        label = {-1: "어제", 0: "오늘", 1: "내일", 2: "모레"}[offset]
        subtitle = f"{day.month}월 {day.day}일 ({_WEEKDAY[day.weekday()]}) · 한국 시간 · {len(listed)}경기"
        footer = "출처: VLR.gg · 경기 목록은 1시간마다 자동 갱신"
        png = await build_schedule_card(f"{label}의 경기 일정", subtitle, listed, footer)
        if png is not None:
            await interaction.followup.send(file=discord.File(BytesIO(png), filename="schedule.png"))
            return
        embed = matches_embed(f"📅 {label}의 경기 일정", listed)
        if not listed:
            embed.description = "이 날은 예정된 경기가 없습니다."
        await interaction.followup.send(embed=embed)
