"""/예측 화면: 경기 선택 → 예측 종류 → 선택지 → 금액 입력."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from bot.embeds.common import error_embed
from bot.embeds.prediction import KIND_KO, market_embed, my_predictions_embed, others_predictions_embed, prediction_lines
from bot.services import odds_model as om
from bot.services.odds_model import CANCEL_FEE_PCT, cancel_fee
from bot.services import prediction_service as ps
from bot.services.economy_service import fmt

log = logging.getLogger("valobot.view.prediction")


def _short(text: str, n: int = 100) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


async def _say(interaction: discord.Interaction, text: str | None = None, **kw) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True, **kw)
    else:
        await interaction.response.send_message(text, ephemeral=True, **kw)


class StakeModal(discord.ui.Modal):
    def __init__(self, market: ps.Market, kind: str, pick: str, label: str, mult: float) -> None:
        super().__init__(title=_short(f"{KIND_KO[kind]} · {label}", 45))
        self.market, self.kind, self.pick, self.label, self.mult = market, kind, pick, label, mult
        self.amount = discord.ui.TextInput(label=f"걸 VP ({om.MIN_STAKE:,}~{om.MAX_STAKE:,}) · 배율 ×{mult:.2f}",
                                           placeholder="예: 100", max_length=6, required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).replace(",", "").strip()
        if not raw.isdigit():
            await _say(interaction, embed=error_embed("숫자만 입력해주세요."))
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pred, bal = await ps.place(guild_id=interaction.guild_id, user_id=interaction.user.id, market=self.market,
                                       kind=self.kind, pick=self.pick, pick_label=self.label, odds=self.mult, stake=int(raw))
        except ps.PredictionError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        win = int(pred.stake * pred.odds)
        await interaction.followup.send(
            f"✅ **{KIND_KO[self.kind]}** `{self.label}` 에 **{fmt(pred.stake)}** 를 걸었어요.\n"
            f"맞히면 **{fmt(win)}** (×{pred.odds:.2f}) · 남은 잔액 {fmt(bal)}\n"
            f"경기 시작 전까지는 `/내예측`에서 취소할 수 있어요 (수수료 10%).", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error("금액 입력 처리 오류", exc_info=error)
        await _say(interaction, embed=error_embed("처리 중 오류가 발생했어요. 잠시 후 다시 시도해주세요."))


class PickSelect(discord.ui.Select):
    def __init__(self, market: ps.Market, kind: str, options: list[tuple[str, str, float]]) -> None:
        self.market, self.kind = market, kind
        self.table = {pick: (label, mult) for pick, label, mult in options}
        super().__init__(placeholder="선택하세요", options=[
            discord.SelectOption(label=_short(f"{label}  ×{mult:.2f}"), value=_short(pick)) for pick, label, mult in options[:25]])

    async def callback(self, interaction: discord.Interaction) -> None:
        pick = self.values[0]
        label, mult = self.table[pick]
        state = self.market.state()
        if state != "open":
            await _say(interaction, embed=error_embed(str(ps.BettingClosed(state))))
            return
        await interaction.response.send_modal(StakeModal(self.market, self.kind, pick, label, mult))


class PickView(discord.ui.View):
    def __init__(self, market: ps.Market, kind: str, options: list[tuple[str, str, float]]) -> None:
        super().__init__(timeout=300)
        self.add_item(PickSelect(market, kind, options))


class ConfirmCancelView(discord.ui.View):
    """수수료가 있으니 한 번 더 확인한 뒤 취소한다."""

    def __init__(self, pred_id: int) -> None:
        super().__init__(timeout=60)
        self.pred_id = pred_id

    @discord.ui.button(label="취소하기", emoji="🚫", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            pred, bal, fee = await ps.cancel(user_id=interaction.user.id, prediction_id=self.pred_id)
        except ps.PredictionError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.edit_original_response(
            content=(f"🚫 `{pred.pick_label}` 예측을 취소했어요. 수수료 **{fmt(fee)}** 를 빼고 **{fmt(pred.stake - fee)}** 를 돌려받았어요. "
                     f"잔액 {fmt(bal)}"), view=None)

    @discord.ui.button(label="그대로 두기", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="예측을 그대로 두었어요.", view=None)


class CancelSelect(discord.ui.Select):
    def __init__(self, preds: list) -> None:
        self.table = {str(p.id): p for p in preds[:25]}
        super().__init__(placeholder=f"취소할 예측 선택 (수수료 {CANCEL_FEE_PCT}%)", options=[
            discord.SelectOption(label=_short(f"{KIND_KO.get(p.kind, p.kind)} · {p.pick_label} · {p.stake:,} VP"), value=str(p.id))
            for p in preds[:25]])

    async def callback(self, interaction: discord.Interaction) -> None:
        pred = self.table[self.values[0]]
        fee = cancel_fee(pred.stake)
        await interaction.response.send_message(
            f"`{pred.pick_label}` ({fmt(pred.stake)}) 예측을 취소할까요?\n"
            f"수수료 **{fmt(fee)}** ({CANCEL_FEE_PCT}%)를 떼고 **{fmt(pred.stake - fee)}** 가 돌아와요.",
            view=ConfirmCancelView(pred.id), ephemeral=True)


class CancelView(discord.ui.View):
    def __init__(self, preds: list) -> None:
        super().__init__(timeout=300)
        self.add_item(CancelSelect(preds))


async def send_my_predictions(interaction: discord.Interaction) -> None:
    preds = await ps.my_recent(interaction.guild_id, interaction.user.id)
    now = datetime.now(timezone.utc)
    cancellable = [p for p in preds if p.status == "open"
                   and om.betting_state(now, p.match.scheduled_at, p.match.status) != "started"]
    await _say(interaction, embed=my_predictions_embed(preds), view=CancelView(cancellable) if cancellable else discord.utils.MISSING)


class MarketView(discord.ui.View):
    def __init__(self, market: ps.Market) -> None:
        super().__init__(timeout=600)
        self.market = market

    async def _open(self, interaction: discord.Interaction, kind: str) -> None:
        m = self.market
        state = m.state()
        if state != "open":
            await _say(interaction, embed=error_embed(str(ps.BettingClosed(state))))
            return
        if kind == "winner":
            opts = [("1", f"{m.team1} 승", m.odds.winner[0]), ("2", f"{m.team2} 승", m.odds.winner[1])]
        elif kind == "score":
            opts = [(s, f"{m.team1} {s.split('-')[0]}:{s.split('-')[1]} {m.team2}", x) for s, x in m.score_options()]
            if not opts:
                await _say(interaction, embed=error_embed("단판 경기는 맵 스코어를 예측할 수 없어요."))
                return
        else:
            opts = [(n, f"{n} ({m.team1})", m.mvp_mult(1)) for n in m.roster1] + [(n, f"{n} ({m.team2})", m.mvp_mult(2)) for n in m.roster2]
            if not opts:
                await _say(interaction, embed=error_embed("두 팀의 로스터 정보가 없어 MVP를 예측할 수 없어요."))
                return
        text = {"winner": "어느 팀이 이길까요?", "score": "맵 스코어를 골라주세요.",
                "mvp": "이 경기의 MVP(레이팅이 가장 높은 선수)를 골라주세요."}[kind]
        await _say(interaction, text, view=PickView(m, kind, opts))

    @discord.ui.button(label="승패", emoji="🏆", style=discord.ButtonStyle.danger)
    async def winner(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "winner")

    @discord.ui.button(label="맵 스코어", emoji="🗺️", style=discord.ButtonStyle.primary)
    async def score(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "score")

    @discord.ui.button(label="MVP", emoji="⭐", style=discord.ButtonStyle.primary)
    async def mvp(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "mvp")

    @discord.ui.button(label="내 예측", emoji="📋", style=discord.ButtonStyle.secondary)
    async def mine(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        preds = await ps.my_for_match(interaction.guild_id, interaction.user.id, self.market.match_id)
        await _say(interaction, prediction_lines(preds) if preds else "이 경기에는 아직 예측이 없어요.")


class MatchSelect(discord.ui.Select):
    def __init__(self, matches: list) -> None:
        opts = []
        for m in matches[:25]:
            when = m.scheduled_at.astimezone(om_tz()).strftime("%m/%d %H:%M") if m.scheduled_at else "시간 미정"
            opts.append(discord.SelectOption(label=_short(f"{m.team1_name} vs {m.team2_name}"),
                                             description=_short(f"{when} · {m.tournament_name or ''}"), value=str(m.vlr_id)))
        super().__init__(placeholder="예측할 경기를 고르세요", options=opts)

    async def callback(self, interaction: discord.Interaction) -> None:
        await show_market(interaction, int(self.values[0]))


def om_tz():
    from bot.services.economy_service import KST
    return KST


class MatchSelectView(discord.ui.View):
    def __init__(self, matches: list) -> None:
        super().__init__(timeout=300)
        self.add_item(MatchSelect(matches))


async def show_market(interaction: discord.Interaction, vlr_id: int) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        market = await ps.load_market(vlr_id)
        mine = await ps.my_for_match(interaction.guild_id, interaction.user.id, market.match_id)
    except ps.PredictionError as exc:
        await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
        return
    state = market.state()
    await interaction.followup.send(embed=market_embed(market, mine, state), view=MarketView(market), ephemeral=True)


class PredictedMatchSelect(discord.ui.Select):
    """/예측현황: 이 서버에 예측이 있는 경기 목록."""

    def __init__(self, rows: list) -> None:
        opts = []
        for m, n in rows[:25]:
            when = m.scheduled_at.astimezone(om_tz()).strftime("%m/%d %H:%M") if m.scheduled_at else "시간 미정"
            opts.append(discord.SelectOption(label=_short(f"{m.team1_name} vs {m.team2_name}"),
                                             description=_short(f"{when} · 예측 {n}건"), value=str(m.id)))
        super().__init__(placeholder="경기를 고르세요", options=opts)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        match, preds = await ps.match_predictions(interaction.guild_id, int(self.values[0]))
        if match is None:
            await interaction.followup.send(embed=error_embed("경기를 찾을 수 없어요."), ephemeral=True)
            return
        await interaction.followup.send(embed=others_predictions_embed(match, preds),
                                        allowed_mentions=discord.AllowedMentions.none())


class PredictedMatchView(discord.ui.View):
    def __init__(self, rows: list) -> None:
        super().__init__(timeout=300)
        self.add_item(PredictedMatchSelect(rows))
