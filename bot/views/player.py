"""선수 화면 버튼: 크로스헤어 코드 복사, ProSettings / VLR 링크."""

from __future__ import annotations

import discord

from bot.database.repository import PlayerDetail
from bot.views.match import VIEW_TIMEOUT


class PlayerView(discord.ui.View):
    def __init__(self, detail: PlayerDetail) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.code = detail.crosshair.code if detail.crosshair else None
        self.nickname = detail.player.nickname
        if not self.code:
            self.remove_item(self.crosshair_code)
        if detail.player.prosettings_url:
            self.add_item(discord.ui.Button(label="ProSettings", url=detail.player.prosettings_url, emoji="🔗"))
        if detail.player.vlr_url:
            self.add_item(discord.ui.Button(label="VLR.gg", url=detail.player.vlr_url, emoji="🔗"))

    @discord.ui.button(label="크로스헤어 코드", emoji="➕", style=discord.ButtonStyle.primary)
    async def crosshair_code(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # 코드 블록으로 보내면 휴대폰에서도 길게 눌러 복사하기 쉽다 (본인에게만 보임)
        await interaction.response.send_message(
            f"**{self.nickname}** 크로스헤어 코드\n```\n{self.code}\n```\n"
            "게임 설정 → 크로스헤어 → 프로필 가져오기에 붙여넣으세요.",
            ephemeral=True,
        )
