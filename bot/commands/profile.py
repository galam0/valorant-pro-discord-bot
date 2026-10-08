"""/프로필 /상점 /꾸미기 /프로필설정 — VP로 사는 프로필 꾸미기."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.autocomplete import team_autocomplete
from bot.services import guild_settings
from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_MAIN, error_embed
from bot.render import images
from bot.render.base import render_enabled
from bot.render.profile_card import render_profile_card
from bot.services import profile_service as ps
from bot.services import shop_catalog as cat
from bot.services.economy_service import fmt

log = logging.getLogger("valobot.cmd.profile")


async def build_card(guild_id: int, member: discord.abc.User) -> tuple[discord.File | None, dict]:
    data = await ps.card_data(guild_id, member.id, member.display_name)
    if not render_enabled():
        return None, data
    avatar = await images.fetch_big(member.display_avatar.replace(size=256, format="png").url, 256)
    png = await asyncio.to_thread(render_profile_card, data, avatar)
    return discord.File(BytesIO(png), filename="profile.png"), data


def text_profile(data: dict) -> discord.Embed:
    e = discord.Embed(title=f"{data['name']} 님의 프로필", color=COLOR_MAIN)
    e.add_field(name="VP", value=fmt(data["vp"]))
    e.add_field(name="서버 순위", value=f"{data['rank']}위")
    e.add_field(name="예측 적중", value=f"{data['pred_win']}/{data['pred_total']}")
    return e


class CustomizeView(discord.ui.View):
    """내가 가진 배경·테두리·칭호 중에서 고른다."""

    def __init__(self, guild_id: int, user: discord.abc.User, have: set[str], current: dict[str, str]) -> None:
        super().__init__(timeout=300)
        self.guild_id, self.user = guild_id, user
        for kind, label in (("theme", "배경"), ("frame", "테두리"), ("title", "칭호")):
            items = [i for i in cat.by_kind(kind) if cat.owned_or_free(i.id, have)]
            sel = discord.ui.Select(placeholder=f"{label} 고르기", options=[
                discord.SelectOption(label=i.name, value=i.id, default=(i.id == current.get(kind))) for i in items[:25]])
            sel.callback = self._make_cb(sel)
            self.add_item(sel)

    def _make_cb(self, sel: discord.ui.Select):
        async def cb(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            try:
                await ps.equip(self.guild_id, self.user.id, sel.values[0])
            except ps.ShopError as exc:
                await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
                return
            file, data = await build_card(self.guild_id, self.user)
            if file is not None:
                await interaction.edit_original_response(content="✅ 적용했어요!", attachments=[file], embed=None, view=self)
            else:
                await interaction.edit_original_response(content="✅ 적용했어요!", embed=text_profile(data), view=self)
        return cb


class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id

    @discord.ui.button(label="꾸미기", emoji="🎨", style=discord.ButtonStyle.primary)
    async def customize(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("내 프로필에서만 꾸밀 수 있어요. `/프로필`을 직접 열어보세요.", ephemeral=True)
            return
        have = await ps.owned(interaction.guild_id, interaction.user.id)
        cur = await ps.current_equipped(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message("무엇을 바꿀까요? (`/상점`에서 더 살 수 있어요)",
                                                view=CustomizeView(interaction.guild_id, interaction.user, have, cur), ephemeral=True)

    @discord.ui.button(label="상점", emoji="🛍️", style=discord.ButtonStyle.secondary)
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_shop(interaction)


class ConfirmBuy(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, item: cat.Item) -> None:
        super().__init__(timeout=60)
        self.guild_id, self.user_id, self.item = guild_id, user_id, item

    @discord.ui.button(label="구매", emoji="✅", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        try:
            bal = await ps.buy(self.guild_id, self.user_id, self.item.id)
        except ps.ShopError as exc:
            await interaction.response.edit_message(content=None, embed=error_embed(str(exc)), view=None)
            return
        await interaction.response.edit_message(
            content=f"🎉 **{cat.KIND_KO[self.item.kind]} · {self.item.name}** 구매 완료! 잔액 {fmt(bal)}\n`/프로필` → 꾸미기에서 적용하세요.",
            embed=None, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="취소했어요.", embed=None, view=None)


class ShopSelect(discord.ui.Select):
    def __init__(self, items: list[cat.Item]) -> None:
        super().__init__(placeholder="사고 싶은 상품 고르기", options=[
            discord.SelectOption(label=f"{cat.KIND_KO[i.kind]} · {i.name}", description=f"{i.price:,} VP", value=i.id) for i in items[:25]])

    async def callback(self, interaction: discord.Interaction) -> None:
        item = cat.BY_ID[self.values[0]]
        await interaction.response.send_message(
            f"**{cat.KIND_KO[item.kind]} · {item.name}** ({item.price:,} VP) 을(를) 살까요?",
            view=ConfirmBuy(interaction.guild_id, interaction.user.id, item), ephemeral=True)


async def send_shop(interaction: discord.Interaction) -> None:
    bal, have = await ps.balance_and_owned(interaction.guild_id, interaction.user.id)
    embed = discord.Embed(title="🛍️ VP 상점", description=f"내 잔액 **{fmt(bal)}**", color=COLOR_INFO)
    for kind in ("theme", "frame", "title"):
        lines = []
        for i in cat.by_kind(kind):
            if i.price == 0:
                continue
            mark = "✅ 보유" if i.id in have else f"{i.price:,} VP"
            lines.append(f"**{i.name}** — {mark}")
        embed.add_field(name=cat.KIND_KO[kind], value="\n".join(lines) or "-", inline=True)
    todo = [i for i in cat.ITEMS if i.price > 0 and i.id not in have]
    view = discord.ui.View(timeout=300)
    if todo:
        view.add_item(ShopSelect(todo))
    else:
        embed.set_footer(text="모든 상품을 가지고 있어요!")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def agent_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    q = current.strip()
    return [app_commands.Choice(name=a, value=a) for a in cat.AGENTS if q in a][:25]


@app_commands.guild_only()
class ProfileCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await guild_settings.check_game_channel(interaction)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return False
        return True

    @app_commands.command(name="프로필", description="내(또는 다른 사람의) VP 프로필 카드를 봅니다.")
    @app_commands.describe(유저="다른 사람의 프로필을 보려면 선택")
    async def profile(self, interaction: discord.Interaction, 유저: discord.Member | None = None) -> None:
        if not await self._guard(interaction):
            return
        target = 유저 or interaction.user
        if target.bot:
            await interaction.response.send_message(embed=error_embed("봇은 프로필이 없어요."), ephemeral=True)
            return
        await interaction.response.defer()
        file, data = await build_card(interaction.guild_id, target)
        view = ProfileView(interaction.user.id) if target.id == interaction.user.id else discord.utils.MISSING
        if file is not None:
            await interaction.followup.send(file=file, view=view)
        else:
            await interaction.followup.send(embed=text_profile(data), view=view)

    @app_commands.command(name="상점", description="VP로 프로필 배경·테두리·칭호를 삽니다.")
    async def shop(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await send_shop(interaction)

    @app_commands.command(name="꾸미기", description="내가 가진 배경·테두리·칭호를 바꿉니다.")
    async def customize(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        have = await ps.owned(interaction.guild_id, interaction.user.id)
        cur = await ps.current_equipped(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message("무엇을 바꿀까요? (`/상점`에서 더 살 수 있어요)",
                                                view=CustomizeView(interaction.guild_id, interaction.user, have, cur), ephemeral=True)

    @app_commands.command(name="프로필설정", description="프로필에 표시할 응원 팀과 최애 요원을 정합니다.")
    @app_commands.describe(응원팀="응원하는 팀", 최애요원="가장 좋아하는 요원")
    @app_commands.autocomplete(응원팀=team_autocomplete, 최애요원=agent_autocomplete)
    async def settings_cmd(self, interaction: discord.Interaction, 응원팀: str | None = None, 최애요원: str | None = None) -> None:
        if not await self._guard(interaction):
            return
        try:
            await ps.set_favs(interaction.guild_id, interaction.user.id, 응원팀, 최애요원)
        except ps.ShopError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.response.send_message("✅ 저장했어요! `/프로필`에서 확인하세요.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCommands(bot))
