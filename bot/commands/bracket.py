"""/대진표 — 대회 대진표 (VLR.gg)."""

from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import COLOR_MAIN, error_embed
from bot.render.cards import build_bracket_card
from bot.scrapers.http import ScrapeError
from bot.scrapers.vlr import ParseError
from bot.services import event_service

log = logging.getLogger("valobot.cmd.bracket")


def _event_url(event_id: int) -> str:
    return f"https://www.vlr.gg/event/{event_id}"


async def _message(result: event_service.EventResult) -> dict:
    """카드(또는 안내) 메시지 내용. view 는 호출하는 쪽에서 붙인다."""
    br = result.bracket
    if not br.sections:
        return {"embed": discord.Embed(
            title=f"🏆 {br.name}",
            description="아직 대진표가 없는 대회입니다.\n(조별 예선·스위스 스테이지 중이거나, 플레이오프가 확정되기 전일 수 있어요)",
            color=COLOR_MAIN, url=_event_url(br.vlr_id))}
    png = await build_bracket_card(br, stale=result.stale)
    if png is not None:
        return {"file": discord.File(BytesIO(png), filename=f"bracket_{br.vlr_id}.png")}
    lines = []
    for sec in br.sections:
        for col in sec.columns:
            for m in col.matches:
                a, b = m.team1, m.team2
                lines.append(f"**{col.label}** · {a.name or '미정'} {a.score if a.score is not None else ''} : "
                             f"{b.score if b.score is not None else ''} {b.name or '미정'}")
    return {"embed": discord.Embed(title=f"🏆 {br.name} 대진표", description="\n".join(lines)[:4000],
                                   color=COLOR_MAIN, url=_event_url(br.vlr_id))}


class EventSelect(discord.ui.Select):
    def __init__(self, candidates: list, current_id: int) -> None:
        options = [
            discord.SelectOption(label=c.name[:100], value=str(c.vlr_id), default=c.vlr_id == current_id,
                                 description=(c.desc or "")[:100] or None)
            for c in candidates[:10]
        ]
        super().__init__(placeholder="다른 대회 보기", options=options, min_values=1, max_values=1)
        self.candidates = candidates

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        event_id = int(self.values[0])
        try:
            bracket, stale = await event_service.get_bracket(event_id)
        except (ScrapeError, ParseError):
            await interaction.followup.send(embed=error_embed("대진표를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."), ephemeral=True)
            return
        result = event_service.EventResult(bracket, self.candidates, stale)
        content = await _message(result)
        view = EventView(self.candidates, event_id) if len(self.candidates) > 1 else discord.utils.MISSING
        await interaction.edit_original_response(embed=content.get("embed"), attachments=[content["file"]] if "file" in content else [],
                                                 view=view)


class EventView(discord.ui.View):
    def __init__(self, candidates: list, current_id: int) -> None:
        super().__init__(timeout=300)
        self.add_item(EventSelect(candidates, current_id))


class BracketCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="대진표", description="대회 대진표를 보여줍니다 (예: 챔피언스, 마스터스 런던).")
    @app_commands.describe(대회="대회 이름 (예: 챔피언스, Masters London, 퍼시픽)")
    async def bracket(self, interaction: discord.Interaction, 대회: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            result = await event_service.find_bracket(대회)
        except event_service.EventNotFound:
            await interaction.followup.send(embed=error_embed(
                f"'{대회}' 대회를 찾을 수 없습니다.\n대회 이름을 영어로 입력하거나 더 짧게 입력해보세요. (예: `champions`, `masters`)"))
            return
        except (ScrapeError, ParseError):
            log.warning("대진표 조회 실패: %s", 대회, exc_info=True)
            await interaction.followup.send(embed=error_embed("대진표를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
            return

        content = await _message(result)
        view = EventView(result.candidates, result.bracket.vlr_id) if len(result.candidates) > 1 else discord.utils.MISSING
        await interaction.followup.send(embed=content.get("embed") or discord.utils.MISSING,
                                        file=content.get("file") or discord.utils.MISSING, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BracketCommands(bot))
