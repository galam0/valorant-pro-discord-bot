"""/ping"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import COLOR_MAIN


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="봇과 데이터베이스 응답 속도를 확인합니다.")
    async def ping(self, interaction: discord.Interaction) -> None:
        # DB가 일시정지 상태면 깨우는 데 몇 초 걸릴 수 있어 먼저 응답을 예약한다
        await interaction.response.defer()
        latency_ms = round(self.bot.latency * 1000)
        if not db.configured:
            db_text = "⚪ 설정 안 됨"
        else:
            db_ms = await db.ping()
            db_text = f"🟢 {db_ms:.0f}ms" if db_ms is not None else "🔴 연결 실패"

        embed = discord.Embed(title="🏓 Pong!", color=COLOR_MAIN)
        embed.add_field(name="Discord", value=f"🟢 {latency_ms}ms", inline=True)
        embed.add_field(name="데이터베이스", value=db_text, inline=True)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
