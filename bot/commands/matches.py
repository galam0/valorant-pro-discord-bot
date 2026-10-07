"""/경기, /전적 — DB에 저장된 경기와 경기 상세(맵별 기록)."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import repository as repo
from bot.database.database import db
from bot.embeds.common import error_embed
from bot.embeds.match import matches_embed
from bot.services import team_service
from bot.views.match import MatchListView, choices_from, send_match_detail

log = logging.getLogger("valobot.cmd.matches")


class MatchCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="경기", description="진행 중·예정된 프로 경기를 보여줍니다.")
    @app_commands.describe(팀="특정 팀의 경기만 보기 (선택)")
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
