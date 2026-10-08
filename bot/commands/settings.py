"""/채널설정 — 게임 채널(명령어 사용 제한)과 알림 채널(예측 정산 결과)을 정한다."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_OK, error_embed
from bot.services import guild_settings
from bot.utils.config import settings

log = logging.getLogger("valobot.cmd.settings")

FIELDS = {"game": "game_channel_id", "notice": "notice_channel_id"}
NAMES = {"game": "게임 채널", "notice": "알림 채널"}


def can_manage(interaction: discord.Interaction) -> bool:
    if interaction.user.id in settings.admin_user_ids:
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


def _mention(cid: int | None) -> str:
    return f"<#{cid}>" if cid else "설정 안 함"


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class SettingsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="채널설정", description="게임 채널(VP·예측·미니게임 전용)과 알림 채널(정산 결과)을 정합니다.")
    @app_commands.describe(종류="무엇을 설정할까요?", 채널="정할 채널 (비워두면 해제)")
    @app_commands.choices(종류=[
        app_commands.Choice(name="게임 채널 — 이 채널에서만 VP·예측·게임 명령어 사용", value="game"),
        app_commands.Choice(name="알림 채널 — 예측 정산 결과를 올릴 채널", value="notice"),
        app_commands.Choice(name="현재 설정 보기", value="show"),
    ])
    async def channel_setting(self, interaction: discord.Interaction, 종류: app_commands.Choice[str],
                              채널: discord.TextChannel | None = None) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        if not can_manage(interaction):
            await interaction.response.send_message(embed=error_embed("서버 관리 권한이 있는 사람만 쓸 수 있어요."), ephemeral=True)
            return
        gid = interaction.guild_id
        kind = 종류.value
        if kind == "show":
            game, notice = await guild_settings.get(gid)
            embed = discord.Embed(title="⚙️ 채널 설정", color=COLOR_INFO)
            embed.add_field(name="게임 채널", value=_mention(game) + ("\nVP·예측·미니게임·프로필 명령어는 여기서만 써요 (관리자 제외)" if game else "\n아무 채널에서나 써요"), inline=False)
            embed.add_field(name="알림 채널", value=_mention(notice) + ("" if notice else "\n정산 결과를 따로 올리지 않아요"), inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if 채널 is not None:
            me = interaction.guild.me
            perms = 채널.permissions_for(me)
            need = perms.view_channel and perms.send_messages and (kind == "game" or perms.embed_links)
            if not need:
                await interaction.response.send_message(
                    embed=error_embed(f"봇이 {채널.mention} 에서 메시지를 보낼 권한이 없어요. (채널 보기·메시지 보내기·링크 임베드)"), ephemeral=True)
                return
        await guild_settings.set_channel(gid, FIELDS[kind], 채널.id if 채널 else None)
        if 채널:
            tail = ("이제 VP·예측·미니게임·프로필 명령어는 이 채널에서만 쓸 수 있어요. (서버 관리자는 어디서나 가능)" if kind == "game"
                    else "예측이 정산되면 결과를 이 채널에 올릴게요.")
            text = f"✅ **{NAMES[kind]}** 을(를) {채널.mention} 로 정했어요.\n{tail}"
        else:
            text = f"✅ **{NAMES[kind]}** 설정을 해제했어요."
        await interaction.response.send_message(embed=discord.Embed(description=text, color=COLOR_OK), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCommands(bot))
