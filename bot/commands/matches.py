"""/경기 — DB에 저장된 진행 중·예정 경기."""

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
                embed = matches_embed(f"🎮 {detail.team.name} 경기", detail.upcoming + detail.recent)
            else:
                async with db.session() as s:
                    upcoming = await repo.get_upcoming_matches(s, limit=8)
                embed = matches_embed("🎮 진행 중 · 예정 경기", upcoming)
                if not upcoming:
                    embed.description = "데이터가 아직 수집되지 않았습니다. (관리자: `/관리 경기갱신`)"
        except Exception:
            log.exception("경기 조회 실패")
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))
            return

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MatchCommands(bot))
