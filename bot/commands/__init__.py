"""Slash Command 모음. 각 파일이 하나의 Cog(명령어 묶음)다."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from bot.embeds.common import error_embed

log = logging.getLogger("valobot.commands")

EXTENSIONS = (
    "bot.commands.general",
    "bot.commands.team",
    "bot.commands.player",
    "bot.commands.matches",
    "bot.commands.admin",
)


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed(message), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed(message), ephemeral=True)
    except discord.HTTPException:
        log.warning("오류 메시지 전송 실패")


def install_error_handler(tree: app_commands.CommandTree) -> None:
    @tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """모든 명령어 오류를 잡아 봇이 죽지 않게 하고 한국어로 안내한다."""
        if isinstance(error, app_commands.CheckFailure):
            await _send_error(interaction, "관리자만 사용할 수 있는 명령어입니다.")
            return
        if isinstance(error, app_commands.CommandOnCooldown):
            await _send_error(interaction, f"잠시 후 다시 시도해주세요. ({error.retry_after:.0f}초)")
            return
        log.error("명령어 처리 중 오류 (/%s)", getattr(interaction.command, "qualified_name", "?"), exc_info=error)
        await _send_error(interaction, "명령어를 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
