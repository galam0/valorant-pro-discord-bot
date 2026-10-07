"""/동전 /주사위 /슬롯 /블랙잭 /퀴즈 — VP 미니게임. (가상 재화, 현금 가치 없음)"""

from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_MAIN, COLOR_OK, COLOR_WARN, error_embed
from bot.services import games, quiz_bank
from bot.services import games_service as gs
from bot.services.economy_service import fmt

log = logging.getLogger("valobot.cmd.games")
_playing: set[tuple[int, int]] = set()      # 진행 중인 블랙잭/퀴즈 (같은 사람이 동시에 여러 판 못 함)

BET = app_commands.Range[int, games.MIN_BET, games.MAX_BET]


def _result_embed(title: str, body: str, stake: int, payout: int, balance: int) -> discord.Embed:
    net = payout - stake
    color = COLOR_OK if net > 0 else (COLOR_INFO if net == 0 else COLOR_WARN)
    embed = discord.Embed(title=title, description=body, color=color)
    embed.add_field(name="결과", value=f"{net:+,} VP" if net else "±0 VP", inline=True)
    embed.add_field(name="잔액", value=fmt(balance), inline=True)
    return embed


def _hand(cards: list[str], hide_second: bool = False) -> str:
    if hide_second:
        return f"`{cards[0]}` `??`"
    return " ".join(f"`{c}`" for c in cards) + f"  (**{games.hand_value(cards)}**)"


class BlackjackView(discord.ui.View):
    def __init__(self, owner: discord.abc.User, guild_id: int, game: games.Blackjack) -> None:
        super().__init__(timeout=90)
        self.owner, self.guild_id, self.game = owner, guild_id, game
        self.message_interaction: discord.Interaction | None = None
        self.finished = False

    def embed(self, final: bool = False, note: str = "") -> discord.Embed:
        g = self.game
        embed = discord.Embed(title="🃏 블랙잭", color=COLOR_MAIN)
        embed.add_field(name="딜러", value=_hand(g.dealer, hide_second=not final), inline=False)
        embed.add_field(name="나", value=_hand(g.player), inline=False)
        embed.set_footer(text=note or f"베팅 {g.total_stake:,} VP · 블랙잭 3:2 · 딜러는 17에서 멈춰요")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("내 게임이 아니에요. `/블랙잭`으로 직접 시작해보세요.", ephemeral=True)
            return False
        return True

    async def _finish(self, interaction: discord.Interaction | None) -> None:
        if self.finished:
            return
        self.finished = True
        self.stop()
        _playing.discard((self.guild_id, self.owner.id))
        g = self.game
        outcome, payout = g.result()
        try:
            bal = await gs.pay(self.guild_id, self.owner.id, payout, "blackjack_win")
        except Exception:
            log.exception("블랙잭 정산 실패")
            return
        text = {"blackjack": "🎉 블랙잭! (3:2)", "win": "✅ 이겼어요!", "push": "🤝 무승부 — 베팅액을 돌려받아요",
                "lose": "❌ 졌어요", "bust": "💥 버스트! (21 초과)"}[outcome]
        embed = _result_embed("🃏 블랙잭", f"{text}\n\n**딜러** {_hand(g.dealer)}\n**나** {_hand(g.player)}", g.total_stake, payout, bal)
        for child in self.children:
            child.disabled = True
        try:
            if interaction is not None:
                await interaction.response.edit_message(embed=embed, view=None)
            elif self.message_interaction is not None:
                await self.message_interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            log.info("블랙잭 결과 메시지를 수정하지 못했어요")

    @discord.ui.button(label="히트", emoji="➕", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.game.hit()
        self.children[2].disabled = True      # 더블은 처음 두 장일 때만
        if self.game.done:
            await self._finish(interaction)
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.game.stand()
        await self._finish(interaction)

    @discord.ui.button(label="더블", emoji="✖️", style=discord.ButtonStyle.danger)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await gs.take_bet(self.guild_id, self.owner.id, self.game.stake, "blackjack_double")
        except gs.GameError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        self.game.double()
        await self._finish(interaction)

    async def on_timeout(self) -> None:
        self.game.stand()          # 시간이 지나면 자동 스탠드
        await self._finish(None)


@app_commands.guild_only()
class GameCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return False
        return True

    @app_commands.command(name="동전", description="동전 던지기. 맞히면 1.95배!")
    @app_commands.describe(금액="걸 VP (10~2000)", 면="앞면 또는 뒷면")
    @app_commands.choices(면=[app_commands.Choice(name="앞", value="앞"), app_commands.Choice(name="뒤", value="뒤")])
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def coin(self, interaction: discord.Interaction, 금액: BET, 면: app_commands.Choice[str]) -> None:
        if not await self._guard(interaction):
            return
        result = games.coin_flip()
        payout = int(금액 * games.COIN_MULT) if result == 면.value else 0
        try:
            bal = await gs.instant(interaction.guild_id, interaction.user.id, 금액, payout, "coin")
        except gs.GameError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        body = f"🪙 **{result}면**이 나왔어요! (내 선택: {면.value})\n" + ("🎉 맞혔어요!" if payout else "아쉬워요…")
        await interaction.response.send_message(embed=_result_embed("🪙 동전 던지기", body, 금액, payout, bal))

    @app_commands.command(name="주사위", description="주사위를 굴려요. 홀/짝은 1.95배, 숫자 맞히기는 5.7배!")
    @app_commands.describe(금액="걸 VP (10~2000)", 선택="홀, 짝, 또는 1~6 중 하나")
    @app_commands.choices(선택=[app_commands.Choice(name=n, value=n) for n in ["홀", "짝", "1", "2", "3", "4", "5", "6"]])
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def dice(self, interaction: discord.Interaction, 금액: BET, 선택: app_commands.Choice[str]) -> None:
        if not await self._guard(interaction):
            return
        roll = random.randint(1, 6)
        payout = games.dice_payout(선택.value, roll, 금액)
        try:
            bal = await gs.instant(interaction.guild_id, interaction.user.id, 금액, payout, "dice")
        except gs.GameError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        body = f"🎲 **{roll}** (내 선택: {선택.value})\n" + ("🎉 맞혔어요!" if payout else "아쉬워요…")
        await interaction.response.send_message(embed=_result_embed("🎲 주사위", body, 금액, payout, bal))

    @app_commands.command(name="슬롯", description="슬롯머신! 3개 일치 5~150배, 2개 일치는 일부 환급")
    @app_commands.describe(금액="걸 VP (10~2000)")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def slots(self, interaction: discord.Interaction, 금액: BET) -> None:
        if not await self._guard(interaction):
            return
        reels = games.slot_spin()
        mult = games.slot_multiplier(reels)
        payout = int(금액 * mult)
        try:
            bal = await gs.instant(interaction.guild_id, interaction.user.id, 금액, payout, "slots")
        except gs.GameError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        note = {0.0: "꽝!", games.SLOT_PAIR_MULT: "2개 일치 — 일부 환급"}.get(mult, f"🎉 3개 일치! ×{mult:g}")
        await interaction.response.send_message(
            embed=_result_embed("🎰 슬롯머신", f"**[ {'  '.join(reels)} ]**\n{note}", 금액, payout, bal))

    @app_commands.command(name="블랙잭", description="딜러와 블랙잭! 블랙잭은 1.5배 보너스")
    @app_commands.describe(금액="걸 VP (10~2000)")
    async def blackjack(self, interaction: discord.Interaction, 금액: BET) -> None:
        if not await self._guard(interaction):
            return
        key = (interaction.guild_id, interaction.user.id)
        if key in _playing:
            await interaction.response.send_message(embed=error_embed("이미 진행 중인 게임이 있어요."), ephemeral=True)
            return
        _playing.add(key)
        try:
            await gs.take_bet(interaction.guild_id, interaction.user.id, 금액, "blackjack")
        except gs.GameError as exc:
            _playing.discard(key)
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        view = BlackjackView(interaction.user, interaction.guild_id, games.Blackjack(stake=금액))
        view.message_interaction = interaction
        if view.game.done:        # 시작하자마자 블랙잭
            await interaction.response.send_message(embed=view.embed(final=True), view=view)
            await view._finish(None)
            return
        await interaction.response.send_message(embed=view.embed(), view=view)

    @app_commands.command(name="퀴즈", description=f"VALORANT 퀴즈! 정답이면 {quiz_bank.REWARD} VP (주 {quiz_bank.WEEKLY_LIMIT}회)")
    async def quiz(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        key = (interaction.guild_id, interaction.user.id)
        if key in _playing:
            await interaction.response.send_message(embed=error_embed("이미 진행 중인 게임이 있어요."), ephemeral=True)
            return
        try:
            left = await gs.quiz_start(interaction.guild_id, interaction.user.id)
        except gs.GameError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        _, question, options, answer = quiz_bank.pick_question()
        _playing.add(key)
        view = QuizView(interaction.user, interaction.guild_id, options, answer, left)
        view.message_interaction = interaction
        embed = discord.Embed(title="❓ VALORANT 퀴즈", description=f"**{question}**", color=COLOR_INFO)
        embed.set_footer(text=f"{quiz_bank.TIME_LIMIT}초 안에 고르세요 · 정답 +{quiz_bank.REWARD} VP · 이번 주 남은 횟수 {left}회")
        await interaction.response.send_message(embed=embed, view=view)


class QuizView(discord.ui.View):
    def __init__(self, owner, guild_id: int, options: list[str], answer: int, left: int) -> None:
        super().__init__(timeout=quiz_bank.TIME_LIMIT)
        self.owner, self.guild_id, self.options, self.answer, self.left = owner, guild_id, options, answer, left
        self.message_interaction: discord.Interaction | None = None
        self.done = False
        for i, text in enumerate(options):
            btn = discord.ui.Button(label=text[:80], style=discord.ButtonStyle.secondary, custom_id=None)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("내 퀴즈가 아니에요. `/퀴즈`로 직접 풀어보세요.", ephemeral=True)
            return False
        return True

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self._resolve(interaction, index)
        return callback

    async def _resolve(self, interaction: discord.Interaction | None, chosen: int | None) -> None:
        if self.done:
            return
        self.done = True
        self.stop()
        _playing.discard((self.guild_id, self.owner.id))
        right = chosen == self.answer
        bal = None
        if right:
            try:
                bal = await gs.pay(self.guild_id, self.owner.id, quiz_bank.REWARD, "quiz")
            except Exception:
                log.exception("퀴즈 보상 지급 실패")
        text = (f"✅ 정답! **+{quiz_bank.REWARD} VP**" + (f" · 잔액 {fmt(bal)}" if bal is not None else "")) if right else \
               ("⏰ 시간 초과!" if chosen is None else "❌ 오답!") + f"\n정답: **{self.options[self.answer]}**"
        embed = discord.Embed(title="❓ VALORANT 퀴즈", description=text, color=COLOR_OK if right else COLOR_WARN)
        embed.set_footer(text=f"이번 주 남은 횟수 {self.left}회")
        try:
            if interaction is not None:
                await interaction.response.edit_message(embed=embed, view=None)
            elif self.message_interaction is not None:
                await self.message_interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            log.info("퀴즈 결과 메시지를 수정하지 못했어요")

    async def on_timeout(self) -> None:
        await self._resolve(None, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCommands(bot))
