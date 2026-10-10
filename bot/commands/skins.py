"""/스킨, /번들 — 발로란트 스킨·번들 정보 (로그인 불필요, 공개 데이터)."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import COLOR_MAIN, error_embed
from bot.services import skin_service as ss

log = logging.getLogger("valobot.cmd.skins")


async def skin_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cat = ss.cached()
    if cat is None:
        return []
    return [app_commands.Choice(name=f"{s.name}{f' · {s.tier}' if s.tier else ''}"[:100], value=s.uuid)
            for s in ss.search_skins(cat, current)]


async def bundle_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cat = ss.cached()
    if cat is None:
        return []
    return [app_commands.Choice(name=b.name[:100], value=b.uuid) for b in ss.search_bundles(cat, current)]


def skin_embed(s: ss.Skin) -> discord.Embed:
    e = discord.Embed(title=s.name, color=s.color if s.color is not None else COLOR_MAIN.value)
    lines = [f"무기 **{s.weapon}**"]
    if s.tier:
        lines.append(f"등급 **{s.tier}**")
    if s.theme:
        lines.append(f"컬렉션 **{s.theme}**")
    lines.append(f"레벨 {s.levels}개 · 색상 변형 {s.chromas}개")
    e.description = "\n".join(lines)
    if s.icon:
        e.set_image(url=s.icon)
    e.set_footer(text="출처: valorant-api.com · 상점 가격/판매 여부는 알 수 없어요")
    return e


def bundle_embed(b: ss.Bundle) -> discord.Embed:
    e = discord.Embed(title=f"🎁 {b.name}", color=COLOR_MAIN)
    parts = [p for p in (b.subtext, b.description) if p]
    if parts:
        e.description = "\n".join(parts)[:600]
    if b.skins:
        lines = [f"· {s.name}" + (f" ({s.tier})" if s.tier else "") for s in b.skins[:15]]
        more = f"\n…외 {len(b.skins) - 15}개" if len(b.skins) > 15 else ""
        e.add_field(name=f"포함 스킨 {len(b.skins)}개", value="\n".join(lines) + more, inline=False)
    else:
        e.add_field(name="포함 스킨", value="구성 정보를 찾지 못했어요.", inline=False)
    if b.icon:
        e.set_image(url=b.icon)
    e.set_footer(text="출처: valorant-api.com")
    return e


class SkinCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _catalog(self, interaction: discord.Interaction) -> ss.Catalog | None:
        await interaction.response.defer()
        try:
            return await ss.load()
        except Exception as exc:
            log.warning("스킨 목록 불러오기 실패: %s: %s", type(exc).__name__, exc)
            await interaction.followup.send(embed=error_embed("스킨 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."))
            return None

    @app_commands.command(name="스킨", description="발로란트 스킨을 검색해 이미지와 정보를 봅니다.")
    @app_commands.describe(이름="스킨 이름 (예: 리버 밴달)")
    @app_commands.autocomplete(이름=skin_autocomplete)
    async def skin(self, interaction: discord.Interaction, 이름: str) -> None:
        cat = await self._catalog(interaction)
        if cat is None:
            return
        found = next((s for s in cat.skins if s.uuid == 이름), None)
        if found is None:
            hits = ss.search_skins(cat, 이름, limit=8)
            if not hits:
                await interaction.followup.send(embed=error_embed(f"'{이름}' 스킨을 찾을 수 없어요."))
                return
            found = hits[0]
            if len(hits) > 1:
                others = ", ".join(s.name for s in hits[1:6])
                await interaction.followup.send(embed=skin_embed(found), content=f"비슷한 스킨: {others}")
                return
        await interaction.followup.send(embed=skin_embed(found))

    @app_commands.command(name="번들", description="발로란트 번들(스킨 묶음)의 구성을 봅니다.")
    @app_commands.describe(이름="번들 이름 (안 쓰면 목록)")
    @app_commands.autocomplete(이름=bundle_autocomplete)
    async def bundle(self, interaction: discord.Interaction, 이름: str | None = None) -> None:
        cat = await self._catalog(interaction)
        if cat is None:
            return
        if not 이름:
            names = "\n".join(f"· {b.name}" for b in cat.bundles[:25])
            e = discord.Embed(title="🎁 번들 목록", description=names or "없음", color=COLOR_MAIN)
            e.set_footer(text=f"전체 {len(cat.bundles)}개 · 이름을 입력하면 자동완성이 떠요")
            await interaction.followup.send(embed=e)
            return
        found = next((b for b in cat.bundles if b.uuid == 이름), None) or next(iter(ss.search_bundles(cat, 이름, 1)), None)
        if found is None:
            await interaction.followup.send(embed=error_embed(f"'{이름}' 번들을 찾을 수 없어요."))
            return
        await interaction.followup.send(embed=bundle_embed(found))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SkinCommands(bot))
