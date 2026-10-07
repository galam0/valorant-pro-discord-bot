"""/선수 — 선수 감도·장비·크로스헤어 (ProSettings)."""

from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.autocomplete import player_autocomplete
from bot.database.database import db
from bot.embeds.common import COLOR_INFO, error_embed
from bot.embeds.player import player_embed
from bot.render.cards import build_player_card, build_player_compare_card, build_player_stats_card
from bot.scrapers.http import ScrapeError
from bot.services import player_service, player_stats_service
from bot.utils.config import settings
from bot.views.player import PlayerView
from bot.worker_bridge import WorkerUnavailable

log = logging.getLogger("valobot.cmd.player")


async def send_player(interaction: discord.Interaction, query: str, *, force: bool = False) -> None:
    """선수 카드를 보낸다 (/선수, /관리 선수갱신 공용). interaction은 defer 된 상태여야 한다."""
    try:
        result = await player_service.get_player(query, force=force)
    except player_service.PlayerNotFound as exc:
        if exc.candidates:
            names = ", ".join(f"`{p.nickname}`" for p in exc.candidates)
            msg = f"'{query}' 선수를 하나로 특정하지 못했습니다.\n혹시 이 선수인가요? {names}"
        else:
            msg = f"'{query}' 선수 정보를 찾을 수 없습니다.\n닉네임 철자를 확인해주세요."
        await interaction.followup.send(embed=error_embed(msg))
        return
    except WorkerUnavailable:
        await interaction.followup.send(embed=error_embed(
            f"'{query}' 선수는 아직 저장된 정보가 없고, 수집 PC가 꺼져 있어 가져올 수 없습니다."))
        return
    except ScrapeError:
        await interaction.followup.send(embed=error_embed("ProSettings에서 정보를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
        return

    notes = []
    if result.guessed_from:
        notes.append(f"🔎 '{result.guessed_from}' → **{result.detail.player.nickname}** 선수로 찾았어요.")
    if result.worker_offline and result.stale:
        notes.append("💤 수집 PC가 꺼져 있어 마지막으로 저장된 설정을 표시합니다.")
    elif result.worker_offline:
        notes.append("💤 수집 PC가 꺼져 있어 설정을 가져오지 못했습니다. PC 수집기를 켠 뒤 다시 시도해주세요.")
    elif result.stale:
        notes.append("⚠️ 최신 정보를 가져오지 못해 이전에 저장된 설정을 표시합니다.")
    elif result.fetch_error:
        notes.append("⚠️ ProSettings에서 설정을 가져오지 못했습니다. 잠시 후 다시 시도해주세요.")
    content = "\n".join(notes) or None

    view = PlayerView(result.detail)
    if result.worker_offline:
        empty = "수집 PC가 꺼져 있어 설정을 가져오지 못했습니다."
    elif result.fetch_error:
        empty = "ProSettings에서 설정을 가져오지 못했습니다."
    else:
        empty = ("아직 등록된 설정이 없는 선수입니다." if not settings.prosettings_enabled
                 else "ProSettings에 등록된 설정이 없는 선수입니다.")
    png = await build_player_card(result.detail, empty_message=empty)
    if png is not None:
        file = discord.File(BytesIO(png), filename=f"player_{result.detail.player.id}.png")
        await interaction.followup.send(content=content, file=file, view=view)
    else:
        await interaction.followup.send(content=content, embed=player_embed(result.detail), view=view)


TIMESPAN_CHOICES = [
    app_commands.Choice(name="최근 30일", value="30d"),
    app_commands.Choice(name="최근 60일", value="60d"),
    app_commands.Choice(name="최근 90일", value="90d"),
    app_commands.Choice(name="전체 기간", value="all"),
]


async def _stats_or_error(interaction: discord.Interaction, query: str, timespan: str):
    """통계를 가져온다. 실패하면 안내 메시지를 보내고 None."""
    try:
        return await player_stats_service.get_player_stats(query, timespan)
    except player_stats_service.PlayerNotFound as exc:
        if exc.candidates:
            names = ", ".join(f"`{p.nickname}`" for p in exc.candidates)
            msg = f"'{query}' 선수를 하나로 특정하지 못했습니다.\n혹시 이 선수인가요? {names}"
        else:
            msg = f"'{query}' 선수 정보를 찾을 수 없습니다.\n닉네임 철자를 확인해주세요. (팀 로스터에 등록된 선수만 검색돼요)"
        await interaction.followup.send(embed=error_embed(msg))
    except player_stats_service.NoVlrProfile as exc:
        await interaction.followup.send(embed=error_embed(f"**{exc.nickname}** 선수는 VLR 선수 정보가 연결돼 있지 않아 통계를 볼 수 없습니다."))
    except ScrapeError:
        await interaction.followup.send(embed=error_embed("VLR에서 선수 통계를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
    return None


async def send_player_stats(interaction: discord.Interaction, query: str, timespan: str) -> bool:
    """VLR 통계 카드를 보낸다. 보냈으면 True."""
    got = await _stats_or_error(interaction, query, timespan)
    if got is None:
        return False
    page, player, guessed, widened = got

    notes = []
    if guessed:
        notes.append(f"🔎 '{query}' → **{player.nickname}** 선수로 찾았어요.")
    if widened:
        notes.append("ℹ️ 선택한 기간에 경기 기록이 없어 전체 기간 통계를 보여드려요.")
    content = "\n".join(notes) or None
    png = await build_player_stats_card(page)
    if png is not None:
        file = discord.File(BytesIO(png), filename=f"player_stats_{page.vlr_id}.png")
        await interaction.followup.send(content=content, file=file)
    else:
        lines = [f"**{a.agent}** · 레이팅 {a.rating} · ACS {a.acs} · K:D {a.kd}" for a in page.agents[:8]]
        embed = discord.Embed(title=f"{page.nickname} 통계", description="\n".join(lines) or "통계가 없습니다.", color=COLOR_INFO)
        await interaction.followup.send(content=content, embed=embed)
    return True


class PlayerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="선수", description="프로 선수의 요원별 통계(레이팅·ACS·K:D 등)를 보여줍니다.")
    @app_commands.describe(닉네임="선수 닉네임 (예: stax, f0rsakeN). 철자가 조금 달라도 찾아요", 기간="통계 기간 (기본: 최근 90일)")
    @app_commands.choices(기간=TIMESPAN_CHOICES)
    @app_commands.autocomplete(닉네임=player_autocomplete)
    async def player(self, interaction: discord.Interaction, 닉네임: str,
                     기간: app_commands.Choice[str] | None = None) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            await send_player_stats(interaction, 닉네임, 기간.value if 기간 else "90d")
            # 감도·장비 설정(ProSettings/관리자 입력)이 이미 저장된 선수는 설정 카드도 같이 보여준다
            if settings.player_command_enabled or interaction.user.id in settings.admin_user_ids:
                await send_player(interaction, 닉네임)
        except Exception:
            log.exception("선수 조회 실패: %s", 닉네임)
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))


    @app_commands.command(name="선수비교", description="두 선수의 VLR 통계(레이팅·ACS·K:D 등)를 나란히 비교합니다.")
    @app_commands.describe(선수1="첫 번째 선수 닉네임", 선수2="두 번째 선수 닉네임", 기간="통계 기간 (기본: 최근 90일)")
    @app_commands.choices(기간=TIMESPAN_CHOICES)
    @app_commands.autocomplete(선수1=player_autocomplete, 선수2=player_autocomplete)
    async def compare_players(self, interaction: discord.Interaction, 선수1: str, 선수2: str,
                              기간: app_commands.Choice[str] | None = None) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            await _compare_players(interaction, 선수1, 선수2, 기간.value if 기간 else "90d")
        except Exception:
            log.exception("선수 비교 실패: %s vs %s", 선수1, 선수2)
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))



async def _compare_players(interaction: discord.Interaction, q1: str, q2: str, timespan: str) -> None:
    got1 = await _stats_or_error(interaction, q1, timespan)
    if got1 is None:
        return
    got2 = await _stats_or_error(interaction, q2, timespan)
    if got2 is None:
        return
    (a, p1, g1, w1), (b, p2, g2, w2) = got1, got2
    if a.vlr_id == b.vlr_id:
        await interaction.followup.send(embed=error_embed("서로 다른 두 선수를 입력해주세요."))
        return
    notes = []
    if g1:
        notes.append(f"🔎 '{q1}' → **{p1.nickname}**")
    if g2:
        notes.append(f"🔎 '{q2}' → **{p2.nickname}**")
    if w1 or w2:
        notes.append("ℹ️ 선택한 기간에 기록이 없는 선수는 전체 기간 통계로 비교해요.")
    png = await build_player_compare_card(a, b)
    content = "\n".join(notes) or None
    if png is not None:
        await interaction.followup.send(content=content, file=discord.File(BytesIO(png), filename="player_compare.png"))
        return
    from bot.render.player_compare_card import METRICS, summarize

    sa, sb = summarize(a), summarize(b)
    lines = [f"**{label}**  {sa.get(key) if sa.get(key) is not None else '-'}  vs  {sb.get(key) if sb.get(key) is not None else '-'}"
             for label, key, *_ in METRICS[:7]]
    embed = discord.Embed(title=f"{a.nickname} vs {b.nickname}", description="\n".join(lines), color=COLOR_INFO)
    await interaction.followup.send(content=content, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCommands(bot))
