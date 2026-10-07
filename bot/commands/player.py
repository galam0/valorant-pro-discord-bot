"""/선수 — 선수 감도·장비·크로스헤어 (ProSettings)."""

from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import error_embed
from bot.embeds.player import player_embed
from bot.render.cards import build_player_card
from bot.scrapers.http import ScrapeError
from bot.services import player_service
from bot.views.player import PlayerView

log = logging.getLogger("valobot.cmd.player")


async def send_player(interaction: discord.Interaction, query: str, *, force: bool = False) -> None:
    """선수 카드를 보낸다 (/선수, /관리 선수갱신 공용). interaction은 defer 된 상태여야 한다."""
    try:
        result = await player_service.get_player(query, force=force)
    except player_service.PlayerNotFound as exc:
        if exc.candidates:
            names = ", ".join(f"`{p.nickname}`" for p in exc.candidates)
            msg = f"'{query}' 선수를 하나로 특정하지 못했습니다.\n혹시 이 선수인가요? {names}"
        else:
            msg = f"'{query}' 선수 정보를 찾을 수 없습니다.\n닉네임 철자를 확인해주세요."
        await interaction.followup.send(embed=error_embed(msg))
        return
    except ScrapeError:
        await interaction.followup.send(embed=error_embed("ProSettings에서 정보를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
        return

    notes = []
    if result.guessed_from:
        notes.append(f"🔎 '{result.guessed_from}' → **{result.detail.player.nickname}** 선수로 찾았어요.")
    if result.stale:
        notes.append("⚠️ 최신 정보를 가져오지 못해 이전에 저장된 설정을 표시합니다.")
    elif result.fetch_error:
        notes.append("⚠️ ProSettings에서 설정을 가져오지 못했습니다. 잠시 후 다시 시도해주세요.")
    content = "\n".join(notes) or None

    view = PlayerView(result.detail)
    empty = ("ProSettings에서 설정을 가져오지 못했습니다." if result.fetch_error
             else "ProSettings에 등록된 설정이 없는 선수입니다.")
    png = await build_player_card(result.detail, empty_message=empty)
    if png is not None:
        file = discord.File(BytesIO(png), filename=f"player_{result.detail.player.id}.png")
        await interaction.followup.send(content=content, file=file, view=view)
    else:
        await interaction.followup.send(content=content, embed=player_embed(result.detail), view=view)


class PlayerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="선수", description="프로 선수의 감도·DPI·장비·크로스헤어를 보여줍니다.")
    @app_commands.describe(닉네임="선수 닉네임 (예: stax, t3xture). 철자가 조금 달라도 찾아요")
    async def player(self, interaction: discord.Interaction, 닉네임: str) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            await send_player(interaction, 닉네임)
        except Exception:
            log.exception("선수 조회 실패: %s", 닉네임)
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCommands(bot))
