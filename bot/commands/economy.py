"""/vp /출석 /vp랭킹 /예측 /내예측 — 서버별 가상 재화(VP)와 경기 예측 게임."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import error_embed
from bot.embeds.prediction import leaderboard_embed, wallet_embed
from bot.services import economy_service as eco
from bot.services import prediction_service as ps
from bot.services import guild_settings
from bot.views.prediction import MatchSelectView, PredictedMatchView, send_my_predictions

log = logging.getLogger("valobot.cmd.economy")


class CheckinView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="출석 (+100 VP)", emoji="📅", style=discord.ButtonStyle.success)
    async def checkin(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        got, bal = await eco.checkin(interaction.guild_id, interaction.user.id)
        rank, total = await eco.rank_info(interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=wallet_embed(bal, rank, total, checked=got, got=100), view=None)


@app_commands.guild_only()
class EconomyCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await guild_settings.check_game_channel(interaction)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return False
        return True

    @app_commands.command(name="vp", description="내 VP 잔액과 서버 순위를 봅니다.")
    async def vp(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        bal = await eco.balance(interaction.guild_id, interaction.user.id)
        rank, total = await eco.rank_info(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=wallet_embed(bal, rank, total), view=CheckinView(), ephemeral=True)

    @app_commands.command(name="출석", description="하루 한 번 100 VP를 받습니다.")
    async def checkin(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        got, bal = await eco.checkin(interaction.guild_id, interaction.user.id)
        rank, total = await eco.rank_info(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=wallet_embed(bal, rank, total, checked=got, got=100), ephemeral=True)

    @app_commands.command(name="vp랭킹", description="이 서버의 VP 랭킹 TOP 10")
    async def vp_rank(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        rows = await eco.leaderboard(interaction.guild_id, 10)
        await interaction.response.send_message(embed=leaderboard_embed(rows, interaction.guild.name))

    @app_commands.command(name="예측", description="다가오는 경기의 승패·맵 스코어·MVP를 VP로 예측합니다.")
    async def predict(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        matches = await ps.upcoming_markets_list()
        if not matches:
            await interaction.followup.send(embed=error_embed("지금 예측할 수 있는 경기가 없어요. (시작 10분 전까지만 가능해요)"), ephemeral=True)
            return
        await interaction.followup.send("🎯 예측할 경기를 골라주세요.", view=MatchSelectView(matches), ephemeral=True)

    @app_commands.command(name="내예측", description="내가 건 예측을 보고, 시작 전이라면 취소합니다.")
    async def my_predictions(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await send_my_predictions(interaction)

    @app_commands.command(name="예측현황", description="이 서버 사람들이 건 예측을 경기별로 봅니다.")
    async def prediction_board(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        rows = await ps.matches_with_predictions(interaction.guild_id)
        if not rows:
            await interaction.followup.send(embed=error_embed("아직 이 서버에 예측이 없어요. `/예측`으로 먼저 걸어보세요!"), ephemeral=True)
            return
        await interaction.followup.send("👥 예측을 볼 경기를 골라주세요.", view=PredictedMatchView(rows), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCommands(bot))
