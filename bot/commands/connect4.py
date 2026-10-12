"""/사목 — 친구와 하는 사목(Connect 4). VP를 쓰지 않는 친선 대결이다."""

from __future__ import annotations

import asyncio
import logging
import random
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.autocomplete import team_autocomplete
from bot.database import repository as repo
from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_MAIN, COLOR_OK, COLOR_WARN, error_embed
from bot.render import connect4_card, images
from bot.render.base import render_enabled
from bot.services import connect4 as c4

log = logging.getLogger("valobot.cmd.connect4")
_RENDER_SEM = asyncio.Semaphore(2)          # 그림 생성은 동시에 2개까지만 (느린 서버에서 봇이 버벅이지 않게)


def _file(data: bytes, name: str) -> discord.File:
    return discord.File(BytesIO(data), filename=name)


class Connect4Invite(discord.ui.View):
    """사목 도전장: 지목된 사람만 수락/거절할 수 있다."""

    def __init__(self, challenger: discord.abc.User, opponent: discord.abc.User,
                 logo=None, team: str | None = None) -> None:
        super().__init__(timeout=120)
        self.challenger, self.opponent = challenger, opponent
        self.logo, self.team = logo, team
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.challenger.id and interaction.data.get("custom_id") == "c4_cancel":
            return True
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("도전받은 사람만 누를 수 있어요.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="수락", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        players = [self.challenger, self.opponent]
        random.shuffle(players)                      # 누가 먼저 둘지는 무작위
        game = Connect4View(players[0], players[1], logo=self.logo, team=self.team)
        game.message = self.message
        embed, files = await game.render()
        await interaction.response.edit_message(content=None, embed=embed, attachments=files, view=game)

    @discord.ui.button(label="거절", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content=None, embed=discord.Embed(description=f"{self.opponent.mention} 님이 사목 도전을 거절했어요.", color=COLOR_WARN),
            view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, custom_id="c4_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content=None, embed=discord.Embed(description="사목 도전을 취소했어요.", color=COLOR_WARN), view=None)

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content=None, view=None, embed=discord.Embed(
                    description=f"{self.opponent.mention} 님이 응답하지 않아 사목 도전이 취소됐어요.", color=COLOR_WARN))
            except discord.HTTPException:
                pass


class Connect4View(discord.ui.View):
    """사목 한 판. 위 버튼 1~7 로 돌을 떨어뜨린다. 차례인 사람만 둘 수 있다."""

    TURN_LIMIT = 180       # 이 시간(초) 동안 안 두면 그 사람이 진다

    def __init__(self, first: discord.abc.User, second: discord.abc.User, logo=None, team: str | None = None) -> None:
        super().__init__(timeout=self.TURN_LIMIT)
        self.players = {1: first, 2: second}          # 1 = 흑(먼저), 2 = 백
        self.logo, self.team = logo, team
        self.board = c4.Board()
        self.last: tuple[int, int] | None = None
        self.result = ""
        self.message: discord.Message | None = None
        self._build()

    def _build(self) -> None:
        self.clear_items()
        b = self.board
        for col in range(c4.COLS):
            btn = discord.ui.Button(label=str(col + 1), style=discord.ButtonStyle.primary,
                                    row=0 if col < 4 else 1, disabled=not b.can_drop(col) or bool(self.result))
            btn.callback = self._drop(col)
            self.add_item(btn)
        give_up = discord.ui.Button(label="기권", emoji="🏳️", style=discord.ButtonStyle.danger, row=1,
                                    disabled=b.over or bool(self.result))
        give_up.callback = self._give_up
        self.add_item(give_up)

    def embed(self, picture: bool = False) -> discord.Embed:
        p1, p2 = self.players[1], self.players[2]
        b = self.board
        head = f"{c4.DISC[1]} 흑 {p1.mention}  vs  {c4.DISC[2]} 백 {p2.mention}"
        if self.result:
            status, color = self.result, COLOR_WARN
        elif b.winner:
            status, color = f"🏆 {c4.DISC[b.winner]} {self.players[b.winner].mention} 님 승리!", COLOR_OK
        elif b.full:
            status, color = "🤝 판이 가득 찼어요. 무승부!", COLOR_INFO
        else:
            status, color = (f"{c4.DISC[b.turn]} {self.players[b.turn].mention} 님 차례 — 번호를 눌러 돌을 넣으세요 "
                             f"({self.TURN_LIMIT // 60}분 안에 안 두면 패배)"), COLOR_MAIN
        e = discord.Embed(title="⚫⚪ 사목" + (f" · {self.team} 판" if self.team else ""), color=color)
        if picture:
            e.description = f"{head}\n\n{status}"
            e.set_image(url="attachment://connect4.png")
        else:
            e.description = f"{head}\n\n{b.text()}\n\n{status}"
        return e

    async def render(self) -> tuple[discord.Embed, list[discord.File]]:
        """판 그림이 든 임베드. 그림을 못 만들면 이모지 판으로."""
        if render_enabled():
            try:
                async with _RENDER_SEM:
                    png = await asyncio.to_thread(connect4_card.render_board, self.board, self.last, self.logo)
                return self.embed(picture=True), [_file(png, "connect4.png")]
            except Exception as exc:
                log.warning("사목 판 그림 실패, 이모지 판으로: %s: %s", type(exc).__name__, exc)
        return self.embed(), []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ids = {p.id for p in self.players.values()}
        if interaction.user.id not in ids:
            await interaction.response.send_message("이 판의 플레이어만 누를 수 있어요. /사목 으로 친구에게 도전해 보세요!", ephemeral=True)
            return False
        return True

    async def _finish_if_over(self, interaction: discord.Interaction) -> None:
        self._build()
        if self.board.over or self.result:
            self.stop()
        await interaction.response.defer()
        embed, files = await self.render()
        await interaction.edit_original_response(embed=embed, attachments=files, view=self)

    def _drop(self, col: int):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.players[self.board.turn].id:
                await interaction.response.send_message("아직 상대 차례예요.", ephemeral=True)
                return
            row = self.board.drop(col)
            if row is None:
                await interaction.response.send_message("그 줄은 꽉 찼어요.", ephemeral=True)
                return
            self.last = (row, col)
            await self._finish_if_over(interaction)
        return callback

    async def _give_up(self, interaction: discord.Interaction) -> None:
        loser = next(n for n, p in self.players.items() if p.id == interaction.user.id)
        self.result = f"🏳️ {self.players[loser].mention} 님이 기권해서 {c4.DISC[3 - loser]} {self.players[3 - loser].mention} 님 승리!"
        await self._finish_if_over(interaction)

    async def on_timeout(self) -> None:
        if self.board.over or self.result:
            return
        late = self.board.turn
        self.result = (f"⏰ {self.players[late].mention} 님이 시간 안에 두지 않아서 "
                       f"{c4.DISC[3 - late]} {self.players[3 - late].mention} 님 승리!")
        self._build()
        if self.message is not None:
            try:
                embed, files = await self.render()
                await self.message.edit(embed=embed, attachments=files, view=self)
            except discord.HTTPException:
                pass


@app_commands.guild_only()
class Connect4Commands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="사목", description="친구와 사목(4개 먼저 잇기) 대결! 상대를 지정하면 도전장을 보내요.")
    @app_commands.describe(상대="같이 할 사람", 팀="판에 새길 팀 로고 (예: T1, 젠지) — 안 쓰면 기본 나무판")
    @app_commands.autocomplete(팀=team_autocomplete)
    async def connect4(self, interaction: discord.Interaction, 상대: discord.Member, 팀: str | None = None) -> None:
        if 상대.bot or 상대.id == interaction.user.id:
            await interaction.response.send_message(embed=error_embed("다른 사람(봇 제외)에게 도전해 주세요."), ephemeral=True)
            return
        logo, team_name = None, None
        if 팀:
            await interaction.response.defer()
            try:
                async with db.session() as s:
                    found = await repo.find_team(s, 팀)
            except Exception as exc:
                log.warning("사목 팀 찾기 실패: %s: %s", type(exc).__name__, exc)
                found = None
            if found is None or found.team is None:
                hint = ("혹시 " + ", ".join(f"`{t.name}`" for t in found.candidates) + " ?") if found and found.candidates else ""
                await interaction.followup.send(embed=error_embed(f"'{팀}' 팀을 찾지 못했어요. {hint}"), ephemeral=True)
                return
            team_name = found.team.name
            if found.team.logo_url:
                logo = await images.fetch_image(found.team.logo_url)
        view = Connect4Invite(interaction.user, 상대, logo=logo, team=team_name)
        e = discord.Embed(title="⚫⚪ 사목 도전장" + (f" · {team_name} 판" if team_name else ""),
                          description=f"{interaction.user.mention} 님이 {상대.mention} 님에게 사목 대결을 신청했어요!\n"
                                      "가로·세로·대각선으로 돌 4개를 먼저 이으면 승리. 2분 안에 수락해 주세요.",
                          color=COLOR_MAIN)
        kw = dict(content=상대.mention, embed=e, view=view, allowed_mentions=discord.AllowedMentions(users=[상대]))
        if interaction.response.is_done():
            view.message = await interaction.followup.send(wait=True, **kw)
        else:
            await interaction.response.send_message(**kw)
            view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Connect4Commands(bot))
