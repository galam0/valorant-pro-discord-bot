"""/스킨, /세트 — 발로란트 스킨·세트(번들) 정보 (로그인 불필요, 공개 데이터). 이미지 카드 + 버튼·선택 메뉴."""

from __future__ import annotations

import asyncio
import logging

from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import COLOR_MAIN, error_embed
from bot.render import images
from bot.render.base import render_enabled
from bot.render.skin_card import render_set_card, render_skin_card
from bot.services import skin_service as ss, tier_emoji

log = logging.getLogger("valobot.cmd.skins")


async def skin_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cat = ss.cached()
    if cat is None:
        return []
    return [app_commands.Choice(name=f"{s.label or s.name}{f' · {s.tier}' if s.tier else ''}"[:100], value=s.uuid)
            for s in ss.search_skins(cat, current)]


async def bundle_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cat = ss.cached()
    if cat is None:
        return []
    return [app_commands.Choice(name=b.name[:100], value=b.uuid) for b in ss.search_bundles(cat, current)]


def skin_embed(s: ss.Skin, idx: int = 0) -> discord.Embed:
    """이미지 카드를 못 만들 때 쓰는 글 버전."""
    e = discord.Embed(title=s.name, color=s.color if s.color is not None else COLOR_MAIN.value)
    lines = [f"무기 **{s.weapon}**"]
    if s.tier:
        lines.append(f"등급 **{s.tier}**")
    if s.theme:
        lines.append(f"컬렉션 **{s.theme}**")
    if ss.price_text(s):
        lines.append(f"가격 **{ss.price_text(s)}** (등급 기준)")
    lines.append(f"레벨 {s.levels}개 · 색상 변형 {s.chromas}개")
    e.description = "\n".join(lines)
    label, image = s.variants[idx][0], s.variants[idx][1]
    if len(s.variants) > 1:
        e.description += f"\n\n색상 **{label}** ({idx + 1}/{len(s.variants)})"
    if image:
        e.set_image(url=image)
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
    return e


class SkinBrowser(discord.ui.View):
    """스킨/세트 화면 하나를 버튼·선택 메뉴로 넘나든다 (명령어를 쓴 사람만 누를 수 있음).

    화면: 세트 목록(list) → 세트(set) → 스킨(skin). 스킨을 바로 열면 skin 에서 시작.
    """

    def __init__(self, cat: ss.Catalog, owner_id: int, skin: ss.Skin | None = None, bundle: ss.Bundle | None = None) -> None:
        super().__init__(timeout=300)
        self.cat, self.owner_id = cat, owner_id
        self.skin, self.bundle, self.idx = skin, bundle, 0
        self.message: discord.Message | None = None
        self._build()

    # -- 화면 상태 -----------------------------------------------------
    @property
    def mode(self) -> str:
        return "skin" if self.skin else "set" if self.bundle else "list"

    def _video(self) -> str | None:
        return self.skin.variants[self.idx][2] if self.skin and len(self.skin.variants[self.idx]) > 2 else None

    def _build(self) -> None:
        self.clear_items()
        if self.mode == "skin":
            s = self.skin
            if len(s.variants) > 1:
                self._button("◀", self._prev)
                self._button("▶", self._next)
            if self._video():
                self._button("🎬 스킨 영상", self._play)
            if self.bundle:
                self._button("📦 세트로", self._back)
                self.add_item(discord.ui.Button(label="🎬 트레일러", url=ss.trailer_url(self.bundle.name)))
        elif self.mode == "set":
            self.add_item(discord.ui.Button(label="🎬 트레일러 (한국어 검색)", url=ss.trailer_url(self.bundle.name)))
            self._button("📋 세트 목록", self._to_list)
        options = self._options()
        if options:
            sel = discord.ui.Select(placeholder="스킨 고르기" if self.mode != "list" else "세트 고르기",
                                    options=options, row=1)
            sel.callback = self._picked
            self.add_item(sel)

    def _button(self, label: str, callback) -> None:
        b = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=0)
        b.callback = callback
        self.add_item(b)

    def _options(self) -> list[discord.SelectOption]:
        if self.mode == "list":
            return [discord.SelectOption(label=b.name[:100], value=b.uuid, description=f"스킨 {len(b.skins)}개"[:100] if b.skins else None)
                    for b in self.cat.bundles[:25]]
        if self.bundle is None:
            return []
        out = []
        for s in self.bundle.skins[:25]:
            desc = " · ".join(x for x in (s.weapon, ss.price_text(s)) if x)
            out.append(discord.SelectOption(label=(s.label or s.name)[:100], value=s.uuid, description=desc[:100] or None,
                                            emoji=tier_emoji.emoji_for(s.tier_icon),
                                            default=bool(self.skin and s.uuid == self.skin.uuid)))
        return out

    # -- 그림 만들기 ---------------------------------------------------
    async def _render(self) -> tuple[discord.File | None, discord.Embed | None]:
        """(이미지 파일, None) 또는 이미지를 못 만들면 (None, 글 Embed)."""
        try:
            if not render_enabled():
                raise RuntimeError("image cards disabled")
            if self.mode == "skin":
                s = self.skin
                weapon, tier = await asyncio.gather(images.fetch_big(s.variants[self.idx][1], 900), images.fetch_image(s.tier_icon))
                png = await asyncio.to_thread(render_skin_card, s, self.idx, weapon, tier)
                return discord.File(BytesIO(png), filename="skin.png"), None
            if self.mode == "set":
                urls = {s.tier_icon for s in self.bundle.skins[:10] if s.tier_icon}
                fetched = await images.fetch_many({u: u for u in urls})
                fetched["bundle"] = await images.fetch_big(self.bundle.icon, 700)
                png = await asyncio.to_thread(render_set_card, self.bundle, fetched)
                return discord.File(BytesIO(png), filename="set.png"), None
        except Exception as exc:
            log.warning("스킨 카드 만들기 실패, 글로 대체: %s: %s", type(exc).__name__, exc)
        return None, self._embed()

    def _embed(self) -> discord.Embed:
        if self.mode == "skin":
            return skin_embed(self.skin, self.idx)
        if self.mode == "set":
            return bundle_embed(self.bundle)
        names = "\n".join(f"· {b.name}" for b in self.cat.bundles[:25])
        e = discord.Embed(title="🎁 세트 목록", description=names or "없음", color=COLOR_MAIN)
        e.set_footer(text=f"전체 {len(self.cat.bundles)}개 · 아래에서 고르거나 /세트 이름 으로 검색해요")
        return e

    async def first_message(self) -> dict:
        file, embed = await self._render()
        kw: dict = {"view": self if self.children else discord.utils.MISSING}
        if file is not None:
            kw["file"] = file
        else:
            kw["embed"] = embed
        return kw

    async def _show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        file, embed = await self._render()
        self._build()
        await interaction.edit_original_response(
            embed=embed, attachments=[file] if file is not None else [], view=self if self.children else None)

    # -- 입력 처리 -----------------------------------------------------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("명령어를 쓴 사람만 누를 수 있어요. 직접 /스킨 이나 /세트 를 써 보세요.", ephemeral=True)
            return False
        return True

    async def _step(self, interaction: discord.Interaction, step: int) -> None:
        self.idx = (self.idx + step) % len(self.skin.variants)
        await self._show(interaction)

    async def _prev(self, interaction: discord.Interaction) -> None:
        await self._step(interaction, -1)

    async def _next(self, interaction: discord.Interaction) -> None:
        await self._step(interaction, 1)

    async def _play(self, interaction: discord.Interaction) -> None:
        url = self._video()
        if not url:
            await interaction.response.send_message("이 스킨은 영상이 없어요.", ephemeral=True)
            return
        # 영상 주소를 그대로 올리면 디스코드가 채팅 안에서 바로 재생해 준다
        await interaction.response.send_message(f"🎬 **{self.skin.name}** · {self.skin.variants[self.idx][0]}\n{url}")

    async def _back(self, interaction: discord.Interaction) -> None:
        self.skin, self.idx = None, 0
        await self._show(interaction)

    async def _to_list(self, interaction: discord.Interaction) -> None:
        self.skin = self.bundle = None
        self.idx = 0
        await self._show(interaction)

    async def _picked(self, interaction: discord.Interaction) -> None:
        value = interaction.data["values"][0]
        if self.mode == "list":
            self.bundle = next((b for b in self.cat.bundles if b.uuid == value), None)
        elif self.bundle is not None:
            self.skin = next((s for s in self.bundle.skins if s.uuid == value), None)
            self.idx = 0
        await self._show(interaction)

    async def on_timeout(self) -> None:
        for child in self.children:
            if not getattr(child, "url", None):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


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

    @app_commands.command(name="스킨", description="발로란트 스킨을 검색해 이미지 카드로 봅니다. (색상 변형·영상 버튼)")
    @app_commands.describe(이름="스킨 이름 (예: 리버 밴달)")
    @app_commands.autocomplete(이름=skin_autocomplete)
    async def skin(self, interaction: discord.Interaction, 이름: str) -> None:
        cat = await self._catalog(interaction)
        if cat is None:
            return
        found = next((s for s in cat.skins if s.uuid == 이름), None)
        extra = None
        if found is None:
            hits = ss.search_skins(cat, 이름, limit=8)
            if not hits:
                await interaction.followup.send(embed=error_embed(f"'{이름}' 스킨을 찾을 수 없어요."))
                return
            found = hits[0]
            extra = f"비슷한 스킨: {', '.join(s.label or s.name for s in hits[1:6])}" if len(hits) > 1 else None
        view = SkinBrowser(cat, interaction.user.id, skin=found)
        kw = await view.first_message()
        view.message = await interaction.followup.send(content=extra, wait=True, **kw)

    @app_commands.command(name="세트", description="발로란트 세트(번들)의 구성을 이미지로 보고, 안에서 스킨을 골라 봅니다.")
    @app_commands.describe(이름="세트 이름 (안 쓰면 목록)")
    @app_commands.autocomplete(이름=bundle_autocomplete)
    async def bundle(self, interaction: discord.Interaction, 이름: str | None = None) -> None:
        cat = await self._catalog(interaction)
        if cat is None:
            return
        found = None
        if 이름:
            found = next((b for b in cat.bundles if b.uuid == 이름), None) or next(iter(ss.search_bundles(cat, 이름, 1)), None)
            if found is None:
                await interaction.followup.send(embed=error_embed(f"'{이름}' 세트를 찾을 수 없어요."))
                return
        view = SkinBrowser(cat, interaction.user.id, bundle=found)
        kw = await view.first_message()
        view.message = await interaction.followup.send(wait=True, **kw)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SkinCommands(bot))
