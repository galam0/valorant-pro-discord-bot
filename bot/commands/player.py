"""/선수 — Phase 4(ProSettings)에서 구현."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import info_embed


class PlayerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="선수", description="VALORANT 프로 선수 설정을 조회합니다.")
    @app_commands.describe(닉네임="선수 닉네임 (예: stax, t3xture)")
    async def player(self, interaction: discord.Interaction, 닉네임: str) -> None:
        await interaction.response.send_message(
            embed=info_embed(f"🔍 **{닉네임}**\n선수 정보 기능은 준비 중입니다. (Phase 4에서 구현 예정)"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCommands(bot))
