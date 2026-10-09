"""/주식 /매수 /매도 /내주식 — VP로 사고파는 팀 가상 주식."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Annotated

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_MAIN, COLOR_OK, error_embed, ts
from bot.render import images
from bot.render.base import render_enabled
from bot.render.stock_card import render_stock_board
from bot.render.stock_chart import render_stock_chart
from bot.services import guild_settings
from bot.services import stock_model as sm
from bot.services import stock_service as ss
from bot.services.economy_service import fmt

log = logging.getLogger("valobot.cmd.stocks")

QTY = app_commands.Range[int, sm.MIN_QTY, sm.MAX_QTY]
SYMBOLS = [app_commands.Choice(name=f"{d.name} · {d.symbol}", value=d.symbol) for d in sm.STOCKS]


def _arrow(pct: float | None) -> str:
    if pct is None or abs(pct) < 0.05:
        return "–"
    return f"{'▲' if pct > 0 else '▼'} {abs(pct):.1f}%"


def board_embed(quotes: list[ss.Quote]) -> discord.Embed:
    lines = [f"`{q.symbol:<3}` **{q.name}** — {q.price:,} VP ({_arrow(q.change_pct)})" for q in quotes]
    e = discord.Embed(title="📈 VP 주식 시세판", description="\n".join(lines), color=COLOR_MAIN)
    e.set_footer(text=f"수수료 {sm.FEE_PCT}% · 주가는 매시 정각에 바뀌어요")
    return e


def trade_embed(kind: str, t: ss.Trade) -> discord.Embed:
    d = sm.BY_SYMBOL[t.symbol]
    if kind == "buy":
        e = discord.Embed(title=f"🟥 {d.name} 매수", color=COLOR_MAIN)
        e.description = (f"**{t.qty}주** × {t.price:,} VP = {t.amount:,} VP\n수수료 {t.fee:,} VP\n"
                         f"합계 **{fmt(t.amount + t.fee)}** 를 냈어요.")
    else:
        e = discord.Embed(title=f"🟦 {d.name} 매도", color=COLOR_INFO)
        pnl = t.profit or 0
        e.description = (f"**{t.qty}주** × {t.price:,} VP = {t.amount:,} VP\n수수료 {t.fee:,} VP\n"
                         f"**{fmt(t.amount - t.fee)}** 를 받았어요.\n"
                         f"이번 거래 손익 {'+' if pnl >= 0 else '-'}{abs(pnl):,} VP")
    e.set_footer(text=f"남은 VP {t.balance:,}")
    return e


def portfolio_embed(rows: list[ss.Position], cash: int, name: str) -> discord.Embed:
    e = discord.Embed(title=f"💼 {name} 님의 주식", color=COLOR_OK)
    if not rows:
        e.description = f"보유한 주식이 없어요. `/주식`으로 시세를 보고 `/매수`로 사보세요!\n현금 {fmt(cash)}"
        return e
    total = 0
    for p in rows:
        total += p.value
        sign = "+" if p.pnl >= 0 else "-"
        e.add_field(name=f"{p.name}", inline=False,
                    value=(f"{p.shares:,}주 · 평균 {p.avg_cost:,.0f} → 현재 {p.price:,} VP\n"
                           f"평가 {p.value:,} VP ({sign}{abs(p.pnl):,} VP, {sign}{abs(p.pnl_pct):.1f}%)"))
    e.description = f"주식 평가액 **{total:,} VP** · 현금 {fmt(cash)}\n총 자산 **{fmt(total + cash)}**"
    e.set_footer(text="평가액은 수수료 전 금액이에요")
    return e


def ranking_embed(rows: list, names: dict[int, str]) -> discord.Embed:
    e = discord.Embed(title="🏆 주식 투자자 순위", color=COLOR_MAIN)
    if not rows:
        e.description = "아직 주식을 가진 사람이 없어요. `/매수`로 첫 투자자가 되어 보세요!"
        return e
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, value, pnl, pct) in enumerate(rows[:10]):
        sign = "+" if pnl >= 0 else "-"
        lines.append(f"{medals[i] if i < 3 else f'`{i + 1}`'} **{names.get(uid, '알 수 없음')}** — 평가 {value:,} VP "
                     f"({sign}{abs(pnl):,} VP · {sign}{abs(pct):.1f}%)")
    e.description = "\n".join(lines)
    e.set_footer(text="지금 가진 주식의 평가손익 기준 · 수수료 전 금액")
    return e


@app_commands.guild_only()
class StockCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await guild_settings.check_game_channel(interaction)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return False
        return True

    @app_commands.command(name="주식", description="인기 6개 팀의 주가(시세판)를 봅니다.")
    async def stocks(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        quotes = await ss.board()
        embed = board_embed(quotes)
        if render_enabled():
            try:
                fetched = await images.fetch_many({q.symbol: q.logo_url for q in quotes})
                png = await asyncio.to_thread(render_stock_board, quotes, fetched)
                await interaction.followup.send(file=discord.File(BytesIO(png), filename="stocks.png"))
                return
            except Exception:
                log.exception("시세판 이미지 생성 실패")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="매수", description="VP로 팀 주식을 삽니다. (수수료 1%)")
    @app_commands.describe(종목="살 팀", 수량="몇 주 (1~500)")
    @app_commands.choices(종목=SYMBOLS)
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def buy(self, interaction: discord.Interaction, 종목: app_commands.Choice[str], 수량: QTY) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        try:
            t = await ss.buy(interaction.guild_id, interaction.user.id, 종목.value, 수량)
        except ss.StockError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.followup.send(embed=trade_embed("buy", t))

    @app_commands.command(name="매도", description="가진 팀 주식을 팝니다. (수수료 1%)")
    @app_commands.describe(종목="팔 팀", 수량="몇 주 (1~500)")
    @app_commands.choices(종목=SYMBOLS)
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def sell(self, interaction: discord.Interaction, 종목: app_commands.Choice[str], 수량: QTY) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        try:
            t = await ss.sell(interaction.guild_id, interaction.user.id, 종목.value, 수량)
        except ss.StockError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.followup.send(embed=trade_embed("sell", t))

    @app_commands.command(name="주식시간", description="다음 주가 변동까지 남은 시간을 봅니다.")
    async def stock_time(self, interaction: discord.Interaction) -> None:
        nxt = ss.next_tick_at()
        e = discord.Embed(title="⏰ 다음 주가 변동", color=COLOR_INFO,
                          description=f"{ts(nxt, 't')} ({ts(nxt, 'R')})\n주가는 **매시 정각**에 바뀌어요.")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="내주식", description="내가 가진 주식과 손익을 봅니다.")
    async def my_stocks(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        rows, cash = await ss.portfolio(interaction.guild_id, interaction.user.id)
        await interaction.followup.send(embed=portfolio_embed(rows, cash, interaction.user.display_name), ephemeral=True)

    @app_commands.command(name="주식순위", description="이 서버에서 주식으로 가장 많이 번 사람을 봅니다.")
    async def stock_rank(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        rows = await ss.ranking(interaction.guild_id)
        names: dict[int, str] = {}
        for uid, *_ in rows[:10]:
            m = interaction.guild.get_member(uid) if interaction.guild else None
            if m is None:
                try:
                    m = await interaction.guild.fetch_member(uid)
                except discord.HTTPException:
                    m = None
            names[uid] = m.display_name if m else "알 수 없음"
        await interaction.followup.send(embed=ranking_embed(rows, names))

    @app_commands.command(name="주식추이", description="주가 변동 그래프를 봅니다. (종목을 안 고르면 전체 비교)")
    @app_commands.describe(종목="한 팀만 보기 (선택)")
    @app_commands.choices(종목=SYMBOLS)
    async def stock_chart(self, interaction: discord.Interaction, 종목: app_commands.Choice[str] | None = None) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        series = await ss.history(종목.value if 종목 else None)
        if not render_enabled():
            lines = [f"**{n}** {v[0]:,} → {v[-1]:,} VP" for n, v in series.items() if v]
            await interaction.followup.send(embed=discord.Embed(title="📊 주가 추이", description="\n".join(lines) or "기록이 없어요.", color=COLOR_INFO))
            return
        title = f"{종목.name.split(' · ')[0]} 주가" if 종목 else "전체 종목 등락률"
        png = await asyncio.to_thread(render_stock_chart, series, title, single=종목 is not None)
        await interaction.followup.send(file=discord.File(BytesIO(png), filename="stock_chart.png"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StockCommands(bot))
