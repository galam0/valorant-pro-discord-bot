"""/동전 /주사위 /슬롯 /블랙잭 /퀴즈 — VP 미니게임. (가상 재화, 현금 가치 없음)

결과는 DB 정산을 먼저 끝낸 뒤 GIF/그림으로 보여준다. 그림 생성이 실패해도 정산은 이미 끝났으므로 안전하다.
"""

from __future__ import annotations

import asyncio
import logging
import random
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_MAIN, COLOR_OK, COLOR_WARN, error_embed
from bot.render import game_anim, images
from bot.render.base import render_enabled
from bot.services import games, quiz_assets, quiz_bank
from bot.services import games_service as gs
from bot.services.economy_service import fmt

log = logging.getLogger("valobot.cmd.games")
_playing: set[tuple[int, int]] = set()      # 진행 중인 블랙잭/퀴즈 (같은 사람이 동시에 여러 판 못 함)

BET = app_commands.Range[int, games.MIN_BET, games.MAX_BET]


def _file(data: bytes, name: str) -> discord.File:
    return discord.File(BytesIO(data), filename=name)


def _result_embed(title: str, body: str, stake: int, payout: int, balance: int) -> discord.Embed:
    net = payout - stake
    color = COLOR_OK if net > 0 else (COLOR_INFO if net == 0 else COLOR_WARN)
    embed = discord.Embed(title=title, description=body, color=color)
    embed.add_field(name="결과", value=f"{net:+,} VP" if net else "±0 VP", inline=True)
    embed.add_field(name="잔액", value=fmt(balance), inline=True)
    return embed


async def _animate(interaction: discord.Interaction, make_gif, title: str, wait: float, result: discord.Embed) -> None:
    """GIF를 먼저 보여주고, 재생이 끝날 즈음 결과 글자를 채운다."""
    if not render_enabled():
        await interaction.followup.send(embed=result)
        return
    try:
        gif = await asyncio.to_thread(make_gif)
    except Exception:
        log.exception("애니메이션 생성 실패")
        await interaction.followup.send(embed=result)
        return
    result.set_image(url="attachment://anim.gif")
    pending = discord.Embed(title=title, description="두근두근…", color=COLOR_INFO)
    pending.set_image(url="attachment://anim.gif")
    await interaction.followup.send(embed=pending, file=_file(gif, "anim.gif"))
    await asyncio.sleep(wait)
    try:
        await interaction.edit_original_response(embed=result)
    except discord.HTTPException:
        log.info("게임 결과 메시지를 수정하지 못했어요")


def _hand(cards: list[str]) -> str:
    return " ".join(f"`{c}`" for c in cards) + f"  (**{games.hand_value(cards)}**)"


# ---------------------------------------------------------------------------
# 블랙잭
# ---------------------------------------------------------------------------


class BlackjackView(discord.ui.View):
    def __init__(self, owner: discord.abc.User, guild_id: int, game: games.Blackjack) -> None:
        super().__init__(timeout=90)
        self.owner, self.guild_id, self.game = owner, guild_id, game
        self.message_interaction: discord.Interaction | None = None
        self.finished = False
        self.pictures = render_enabled()

    def text_embed(self, hide: bool = True) -> discord.Embed:
        g = self.game
        embed = discord.Embed(title="🃏 블랙잭", color=COLOR_MAIN)
        embed.add_field(name="딜러", value=f"`{g.dealer[0]}` `??`" if hide else _hand(g.dealer), inline=False)
        embed.add_field(name="나", value=_hand(g.player), inline=False)
        embed.set_footer(text=f"베팅 {g.total_stake:,} VP · 블랙잭 3:2 · 딜러는 17에서 멈춰요")
        return embed

    async def table(self) -> tuple[discord.Embed, list[discord.File]]:
        """진행 중 화면 (그림이 안 되면 글)."""
        if not self.pictures:
            return self.text_embed(), []
        try:
            png = await asyncio.to_thread(game_anim.table_png, self.game.player, self.game.dealer, True)
        except Exception:
            log.exception("블랙잭 그림 생성 실패")
            return self.text_embed(), []
        embed = discord.Embed(title="🃏 블랙잭", color=COLOR_MAIN)
        embed.set_image(url="attachment://table.png")
        embed.set_footer(text=f"베팅 {self.game.total_stake:,} VP · 블랙잭 3:2 · 딜러는 17에서 멈춰요")
        return embed, [_file(png, "table.png")]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("내 게임이 아니에요. `/블랙잭`으로 직접 시작해보세요.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction: discord.Interaction | None) -> None:
        """게임 종료: 정산 → (딜러 카드 공개 GIF) → 결과 표시."""
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
        result = _result_embed("🃏 블랙잭", text, g.total_stake, payout, bal)

        async def edit(**kw) -> None:
            try:
                if interaction is not None and not interaction.response.is_done():
                    await interaction.response.edit_message(view=None, **kw)
                elif interaction is not None:
                    await interaction.edit_original_response(view=None, **kw)
                elif self.message_interaction is not None:
                    await self.message_interaction.edit_original_response(view=None, **kw)
            except discord.HTTPException:
                log.info("블랙잭 메시지를 수정하지 못했어요")

        if not self.pictures:
            result.add_field(name="딜러", value=_hand(g.dealer), inline=False)
            result.add_field(name="나", value=_hand(g.player), inline=False)
            await edit(embed=result)
            return
        try:
            gif = await asyncio.to_thread(game_anim.finish_gif, g.player, g.dealer)
        except Exception:
            log.exception("블랙잭 결과 그림 생성 실패")
            result.add_field(name="딜러", value=_hand(g.dealer), inline=False)
            result.add_field(name="나", value=_hand(g.player), inline=False)
            await edit(embed=result)
            return
        pending = discord.Embed(title="🃏 블랙잭", description="딜러 차례…", color=COLOR_MAIN)
        pending.set_image(url="attachment://anim.gif")
        result.set_image(url="attachment://anim.gif")
        await edit(embed=pending, attachments=[_file(gif, "anim.gif")])
        await asyncio.sleep(1.0 + 0.75 * max(0, len(g.dealer) - 1))
        await edit(embed=result)

    @discord.ui.button(label="히트", emoji="➕", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.game.hit()
        self.children[2].disabled = True      # 더블은 처음 두 장일 때만
        if self.game.done:
            await self.finish(interaction)
            return
        embed, files = await self.table()
        await interaction.response.edit_message(embed=embed, attachments=files, view=self)

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.game.stand()
        await self.finish(interaction)

    @discord.ui.button(label="더블", emoji="✖️", style=discord.ButtonStyle.danger)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await gs.take_bet(self.guild_id, self.owner.id, self.game.stake, "blackjack_double")
        except gs.GameError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        self.game.double()
        await self.finish(interaction)

    async def on_timeout(self) -> None:
        self.game.stand()          # 시간이 지나면 자동 스탠드
        await self.finish(None)


# ---------------------------------------------------------------------------
# 퀴즈
# ---------------------------------------------------------------------------


class QuizView(discord.ui.View):
    def __init__(self, owner, guild_id: int, options: list[str], answer: int, left: int, *,
                 visual: quiz_assets.VisualQuiz | None = None, art=None) -> None:
        super().__init__(timeout=quiz_bank.TIME_LIMIT)
        self.owner, self.guild_id, self.options, self.answer, self.left = owner, guild_id, options, answer, left
        self.visual, self.art = visual, art
        self.message_interaction: discord.Interaction | None = None
        self.done = False
        for i, text in enumerate(options):
            btn = discord.ui.Button(label=text[:80], style=discord.ButtonStyle.secondary)
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
        files: list[discord.File] = []
        if self.visual is not None and self.art is not None:   # 정답 공개: 실루엣 대신 진짜 그림
            try:
                png = await asyncio.to_thread(game_anim.quiz_image, self.art, silhouette=False, caption=self.visual.answer_label)
                files = [_file(png, "reveal.png")]
                embed.set_image(url="attachment://reveal.png")
            except Exception:
                log.exception("퀴즈 정답 그림 생성 실패")
        try:
            if interaction is not None:
                await interaction.response.edit_message(embed=embed, attachments=files, view=None)
            elif self.message_interaction is not None:
                await self.message_interaction.edit_original_response(embed=embed, attachments=files, view=None)
        except discord.HTTPException:
            log.info("퀴즈 결과 메시지를 수정하지 못했어요")

    async def on_timeout(self) -> None:
        await self._resolve(None, None)


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
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def coin(self, interaction: discord.Interaction, 금액: BET, 면: app_commands.Choice[str]) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        result = games.coin_flip()
        payout = int(금액 * games.COIN_MULT) if result == 면.value else 0
        try:
            bal = await gs.instant(interaction.guild_id, interaction.user.id, 금액, payout, "coin")
        except gs.GameError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        body = f"🪙 **{result}면**이 나왔어요! (내 선택: {면.value})\n" + ("🎉 맞혔어요!" if payout else "아쉬워요…")
        await _animate(interaction, lambda: game_anim.coin_gif(result), "🪙 동전 던지기", 3.0,
                       _result_embed("🪙 동전 던지기", body, 금액, payout, bal))

    @app_commands.command(name="주사위", description="주사위를 굴려요. 홀/짝은 1.95배, 숫자 맞히기는 5.7배!")
    @app_commands.describe(금액="걸 VP (10~2000)", 선택="홀, 짝, 또는 1~6 중 하나")
    @app_commands.choices(선택=[app_commands.Choice(name=n, value=n) for n in ["홀", "짝", "1", "2", "3", "4", "5", "6"]])
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def dice(self, interaction: discord.Interaction, 금액: BET, 선택: app_commands.Choice[str]) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        roll = random.randint(1, 6)
        payout = games.dice_payout(선택.value, roll, 금액)
        try:
            bal = await gs.instant(interaction.guild_id, interaction.user.id, 금액, payout, "dice")
        except gs.GameError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        body = f"🎲 **{roll}** (내 선택: {선택.value})\n" + ("🎉 맞혔어요!" if payout else "아쉬워요…")
        await _animate(interaction, lambda: game_anim.dice_gif(roll), "🎲 주사위", 2.6,
                       _result_embed("🎲 주사위", body, 금액, payout, bal))

    @app_commands.command(name="슬롯", description="슬롯머신! 3개 일치 5~150배, 2개 일치는 일부 환급")
    @app_commands.describe(금액="걸 VP (10~2000)")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def slots(self, interaction: discord.Interaction, 금액: BET) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        reels = games.slot_spin()
        mult = games.slot_multiplier(reels)
        payout = int(금액 * mult)
        try:
            bal = await gs.instant(interaction.guild_id, interaction.user.id, 금액, payout, "slots")
        except gs.GameError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        note = {0.0: "꽝!", games.SLOT_PAIR_MULT: "2개 일치 — 일부 환급"}.get(mult, f"🎉 3개 일치! ×{mult:g}")
        await _animate(interaction, lambda: game_anim.slot_gif(reels), "🎰 슬롯머신", 3.4,
                       _result_embed("🎰 슬롯머신", f"**[ {'  '.join(reels)} ]**\n{note}", 금액, payout, bal))

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
        await interaction.response.defer()
        try:
            await gs.take_bet(interaction.guild_id, interaction.user.id, 금액, "blackjack")
        except gs.GameError as exc:
            _playing.discard(key)
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        view = BlackjackView(interaction.user, interaction.guild_id, games.Blackjack(stake=금액))
        view.message_interaction = interaction
        g = view.game
        embed, files = view.text_embed(), []
        if view.pictures:
            try:
                gif = await asyncio.to_thread(game_anim.deal_gif, g.player, g.dealer)
                embed = discord.Embed(title="🃏 블랙잭", description="카드를 나눠줘요…", color=COLOR_MAIN)
                embed.set_image(url="attachment://anim.gif")
                embed.set_footer(text=f"베팅 {g.total_stake:,} VP · 블랙잭 3:2 · 딜러는 17에서 멈춰요")
                files = [_file(gif, "anim.gif")]
            except Exception:
                log.exception("블랙잭 딜 그림 생성 실패")
        if g.done:        # 시작하자마자 블랙잭
            await interaction.followup.send(embed=embed, files=files)
            await asyncio.sleep(2.0)
            await view.finish(None)
            return
        await interaction.followup.send(embed=embed, files=files, view=view)

    @app_commands.command(name="퀴즈", description=f"VALORANT 퀴즈(글·블라인드·스킨 랜덤)! 정답이면 {quiz_bank.REWARD} VP (주 {quiz_bank.WEEKLY_LIMIT}회)")
    async def quiz(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        key = (interaction.guild_id, interaction.user.id)
        if key in _playing:
            await interaction.response.send_message(embed=error_embed("이미 진행 중인 게임이 있어요."), ephemeral=True)
            return
        await interaction.response.defer()
        kind = random.choice(["text", "agent", "agent", "weapon", "skin"])    # 종류는 항상 랜덤
        if kind != "text" and not render_enabled():
            kind = "text"

        # 문제와 그림을 먼저 준비한다 (그림 준비에 실패하면 도전 횟수를 쓰기 전에 글 퀴즈로 바꾼다)
        visual, art = None, None
        if kind != "text":
            try:
                visual = await quiz_assets.make_visual(kind)
                art = await images.fetch_big(visual.art_url)
                if art is None:
                    raise RuntimeError("그림을 받지 못했어요")
                silhouette_png = await asyncio.to_thread(game_anim.quiz_image, art, silhouette=kind != "skin")
            except Exception as exc:
                log.warning("그림 퀴즈 준비 실패 → 글 퀴즈로 대체: %s: %s", type(exc).__name__, exc)
                visual, art, kind = None, None, "text"
        try:
            left = await gs.quiz_start(interaction.guild_id, interaction.user.id)
        except gs.GameError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        _playing.add(key)
        if visual is None:
            _, question, options, answer = quiz_bank.pick_question()
            view = QuizView(interaction.user, interaction.guild_id, options, answer, left)
            embed = discord.Embed(title="❓ VALORANT 퀴즈", description=f"**{question}**", color=COLOR_INFO)
            files = []
        else:
            view = QuizView(interaction.user, interaction.guild_id, visual.options, visual.answer, left, visual=visual, art=art)
            title = "🕶️ 블라인드 퀴즈" if visual.kind != "skin" else "🎨 스킨 퀴즈"
            embed = discord.Embed(title=title, description=f"**{visual.question}**", color=COLOR_INFO)
            embed.set_image(url="attachment://quiz.png")
            files = [_file(silhouette_png, "quiz.png")]
        embed.set_footer(text=f"{quiz_bank.TIME_LIMIT}초 안에 고르세요 · 정답 +{quiz_bank.REWARD} VP · 이번 주 남은 횟수 {left}회")
        view.message_interaction = interaction
        await interaction.followup.send(embed=embed, files=files, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCommands(bot))
