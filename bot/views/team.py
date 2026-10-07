"""팀 화면의 선택 메뉴·링크 버튼."""

from __future__ import annotations

import discord

from bot.database.repository import TeamDetail
from bot.views.match import VIEW_TIMEOUT, MatchOpenSelect, choices_from


class TeamView(discord.ui.View):
    def __init__(self, detail: TeamDetail) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        choices = choices_from(detail.upcoming + detail.recent, detail.team.id)
        if choices:
            self.add_item(MatchOpenSelect(choices, placeholder="경기 기록 보기 (맵별 K/D/A)", row=0))
        if detail.team.vlr_url:
            self.add_item(discord.ui.Button(label="VLR.gg", url=detail.team.vlr_url, emoji="🔗", row=1))
