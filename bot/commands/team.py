"""/팀 — DB에 저장된 팀 정보 조회 (사이트에 직접 요청하지 않음)."""

from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.autocomplete import team_autocomplete
from bot.database.database import db
from bot.embeds.common import error_embed
from bot.embeds.team import team_embed
from bot.render.cards import build_team_card, build_team_maps_card
from bot.services import team_maps_service, team_service
from bot.views.team import TeamView

log = logging.getLogger("valobot.cmd.team")


class TeamCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="팀", description="VALORANT 프로팀 정보를 조회합니다.")
    @app_commands.describe(이름="팀 이름 또는 별칭 (예: T1, 젠지, DRX)")
    @app_commands.autocomplete(이름=team_autocomplete)
    async def team(self, interaction: discord.Interaction, 이름: str) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer()

        try:
            detail, candidates = await team_service.get_team(이름)
        except Exception:
            log.exception("팀 조회 실패: %s", 이름)
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))
            return

        if detail is None:
            if candidates:
                names = ", ".join(f"`{t.name}`" for t in candidates)
                msg = f"'{이름}'에 해당하는 팀을 하나로 특정하지 못했습니다.\n혹시 이 팀인가요? {names}"
            else:
                msg = f"'{이름}' 팀을 찾을 수 없습니다.\n아직 수집되지 않은 팀일 수 있어요. (관리자: `/관리 팀갱신 {이름}`)"
            await interaction.followup.send(embed=error_embed(msg))
            return

        png = await build_team_card(detail)
        if png is not None:
            file = discord.File(BytesIO(png), filename=f"team_{detail.team.vlr_id}.png")
            await interaction.followup.send(file=file, view=TeamView(detail))
        else:  # 폰트가 없거나 이미지 생성 실패 → 텍스트 Embed
            await interaction.followup.send(embed=team_embed(detail), view=TeamView(detail))

    @app_commands.command(name="팀맵", description="팀의 맵별 승률·공격/수비 라운드 승률을 보여줍니다. (VLR.gg)")
    @app_commands.describe(이름="팀 이름 또는 별칭 (예: T1, 젠지)", 기간="통계 기간")
    @app_commands.choices(기간=[app_commands.Choice(name=n, value=v) for v, n in team_maps_service.PERIOD_KO.items()])
    @app_commands.autocomplete(이름=team_autocomplete)
    @app_commands.checks.cooldown(1, 5)
    async def team_maps(self, interaction: discord.Interaction, 이름: str, 기간: app_commands.Choice[str] | None = None) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer()
        period = 기간.value if 기간 else "180"
        try:
            team, stats, guessed, widened = await team_maps_service.get_team_maps(이름, period)
        except team_maps_service.TeamNotFound as exc:
            names = ", ".join(f"`{t.name}`" for t in exc.candidates)
            msg = f"'{이름}' 팀을 찾을 수 없습니다." + (f"\n혹시 이 팀인가요? {names}" if names else "")
            await interaction.followup.send(embed=error_embed(msg))
            return
        except Exception:
            log.exception("팀 맵 통계 실패: %s", 이름)
            await interaction.followup.send(embed=error_embed("VLR에서 맵 통계를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
            return
        label = team_maps_service.PERIOD_KO["all" if widened else period]
        note = "ℹ️ 선택한 기간에 경기 기록이 없어 전체 기간 통계를 보여드려요." if widened else None
        png = await build_team_maps_card(team, stats, label)
        if png is not None:
            await interaction.followup.send(content=note, file=discord.File(BytesIO(png), filename="team_maps.png"))
            return
        lines = [f"**{m.map_name}** {m.games}경기 · 승률 {m.win_pct}% ({m.wins}-{m.losses})" for m in stats[:12]]
        await interaction.followup.send(embed=discord.Embed(title=f"🗺️ {team.name} 맵 통계 ({label})", description="\n".join(lines) or "기록 없음"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TeamCommands(bot))
