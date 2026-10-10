"""/상점 일일상점 · 야시장 · 연동상태 · 연동해제 — 발로란트 개인 상점.

지금은 허용된 데이터 제공자가 없어서 상점 조회는 '지원하지 않음'을 안내한다 (valorant_shop_service 참고).
모든 응답은 본인에게만 보이게(ephemeral) 보낸다.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.database import valorant_shop as store
from bot.database.database import db
from bot.embeds.common import COLOR_MAIN, error_embed
from bot.services import valorant_shop_service as vs

log = logging.getLogger("valobot.cmd.valorant_shop")


def shop_embed(result: vs.ShopResult, night_market: bool) -> discord.Embed:
    e = discord.Embed(title="🌙 야시장" if night_market else "🛒 일일 상점", description=result.note, color=COLOR_MAIN)
    if not result.items:
        e.description = (f"{e.description}\n" if e.description else "") + "표시할 상품이 없어요."
    for i, it in enumerate(result.items[:12], 1):
        parts = []
        if it.price is not None:
            parts.append(f"{it.price:,} VP")
        if it.discount_pct:
            parts.append(f"-{it.discount_pct}%" + (f" (원가 {it.original_price:,})" if it.original_price else ""))
        e.add_field(name=f"{i}. {it.name}", value=" · ".join(parts) or "가격 정보 없음", inline=True)
    return e


class ValorantShop(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    shop = app_commands.Group(name="상점", description="발로란트 개인 상점")

    async def _status(self, user_id: int) -> str | None:
        async with db.session() as s:
            row = await store.get(s, user_id)
        return row.status if row else None

    @shop.command(name="연동", description="개인 상점 계정 연동을 시작합니다.")
    async def link(self, interaction: discord.Interaction) -> None:
        if not vs.provider.available:       # 공식으로 허용된 연동 방식이 없으면 시작하지 않는다
            await interaction.response.send_message(vs.UNSUPPORTED, ephemeral=True)
            return
        try:
            url = await vs.provider.begin_link(interaction.user.id)
        except Exception as exc:
            log.warning("연동 시작 실패: %s", type(exc).__name__)
            await interaction.response.send_message("연동을 시작하지 못했어요. 잠시 후 다시 시도해주세요.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"아래 **공식 로그인 페이지**에서 직접 인증해주세요. 봇에는 비밀번호를 입력하지 마세요.\n{url}", ephemeral=True)

    @shop.command(name="연동상태", description="개인 상점 연동 상태를 확인합니다.")
    async def link_status(self, interaction: discord.Interaction) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        state = vs.link_state(await self._status(interaction.user.id), vs.provider)
        text = vs.STATE_TEXT.get(state) or f"연동됨 · 제공자 `{vs.provider.name}`"
        await interaction.response.send_message(text, ephemeral=True)

    @shop.command(name="연동해제", description="저장된 상점 연동 정보를 삭제합니다.")
    async def unlink(self, interaction: discord.Interaction) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        async with db.session() as s:
            removed = await store.unlink(s, interaction.user.id)
            await s.commit()
        await interaction.response.send_message("연동 정보를 삭제했어요." if removed else "삭제할 연동 정보가 없어요.", ephemeral=True)

    @shop.command(name="일일상점", description="내 일일 상점을 봅니다.")
    async def daily(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, night_market=False)

    @shop.command(name="야시장", description="내 야시장을 봅니다.")
    async def night(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, night_market=True)

    async def _show(self, interaction: discord.Interaction, *, night_market: bool) -> None:
        if not vs.provider.available:       # 제공자가 없으면 DB도 건드리지 않고 바로 안내
            await interaction.response.send_message(vs.UNSUPPORTED, ephemeral=True)
            return
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        uid = interaction.user.id
        state = vs.link_state(await self._status(uid), vs.provider)
        if state != "linked":
            await interaction.followup.send(vs.STATE_TEXT[state], ephemeral=True)
            return
        try:
            result = await (vs.provider.get_night_market(uid) if night_market else vs.provider.get_daily_store(uid))
        except vs.AuthExpired:
            await self._record(uid, "auth_expired", expired=True)
            await interaction.followup.send(vs.STATE_TEXT["expired"], ephemeral=True)
            return
        except Exception as exc:
            log.warning("개인 상점 조회 실패: %s", type(exc).__name__)     # 예외 내용은 남기지 않는다 (인증 정보 유출 방지)
            await self._record(uid, "provider_error")
            await interaction.followup.send("상점 조회 중 오류가 났어요. 잠시 후 다시 시도해주세요.", ephemeral=True)
            return
        await self._record(uid, None)
        await interaction.followup.send(embed=shop_embed(result, night_market), ephemeral=True)

    async def _record(self, uid: int, error: str | None, *, expired: bool = False) -> None:
        try:
            async with db.session() as s:
                await store.record_check(s, uid, error, expired=expired)
                await s.commit()
        except Exception as exc:
            log.warning("상점 조회 기록 실패: %s", type(exc).__name__)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ValorantShop(bot))
