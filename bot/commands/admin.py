"""/관리 — 관리자 전용 데이터 갱신·상태 확인.

권한: ADMIN_USER_IDS 에 있는 사용자, 또는 서버 관리자 권한(Administrator)이 있는 사용자.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands.player import send_player
from bot.database import repository as repo
from bot.database.database import db
from bot.embeds.common import COLOR_INFO, COLOR_OK, error_embed, ts
from bot.scrapers.http import ScrapeError
from bot.scrapers.vlr import ParseError
from bot.services import match_service, team_service
from bot.utils.aliases import MAJOR_TEAMS
from bot.utils.config import settings
from bot.worker_bridge import bridge

log = logging.getLogger("valobot.cmd.admin")


def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id in settings.admin_user_ids:
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.administrator)


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class AdminGroup(app_commands.Group, name="관리", description="관리자 전용 명령어"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot
        self.started_at = time.time()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_admin(interaction):
            raise app_commands.CheckFailure()
        return True

    @app_commands.command(name="팀갱신", description="VLR.gg에서 팀 정보(로스터·경기)를 다시 가져옵니다.")
    @app_commands.describe(팀="팀 이름, 별칭 또는 VLR 팀 ID (예: T1, 젠지, 14)")
    @app_commands.checks.cooldown(1, 20)
    async def refresh_team(self, interaction: discord.Interaction, 팀: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await team_service.refresh_team(팀)
        except team_service.TeamNotFound:
            await interaction.followup.send(embed=error_embed(f"VLR.gg에서 '{팀}' 팀을 찾을 수 없습니다."))
            return
        except ParseError as exc:
            await interaction.followup.send(embed=error_embed(f"페이지 구조를 읽지 못했습니다 (사이트 변경 가능성).\n`{exc}`"))
            return
        except ScrapeError as exc:
            await interaction.followup.send(embed=error_embed(f"VLR.gg 요청에 실패했습니다.\n`{exc}`"))
            return

        embed = discord.Embed(title="✅ 팀 갱신 완료", color=COLOR_OK)
        embed.add_field(name="팀", value=f"{result.name} (VLR #{result.vlr_id})", inline=False)
        embed.add_field(name="로스터", value=f"{result.roster_count}명", inline=True)
        embed.add_field(name="경기", value=f"{result.match_count}개", inline=True)
        if result.note:
            embed.add_field(name="참고", value=result.note, inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="전체팀갱신", description="여러 팀을 한 번에 VLR.gg에서 다시 가져옵니다 (몇 분 걸림).")
    @app_commands.describe(대상="저장된 팀만 갱신할지, 주요 리그 팀을 모두 가져올지")
    @app_commands.choices(대상=[
        app_commands.Choice(name="저장된 팀 (빠름)", value="saved"),
        app_commands.Choice(name="주요 리그 팀 전체 (VCT 4개 리그)", value="major"),
    ])
    async def refresh_all_teams(self, interaction: discord.Interaction, 대상: app_commands.Choice[str]) -> None:
        if team_service.bulk_refresh_running():
            await interaction.response.send_message(embed=error_embed("이미 전체 갱신이 진행 중입니다."), ephemeral=True)
            return

        if 대상.value == "saved":
            queries = await team_service.saved_team_queries()
            if not queries:
                await interaction.response.send_message(
                    embed=error_embed("저장된 팀이 없습니다. '주요 리그 팀 전체'로 먼저 가져와 주세요."), ephemeral=True
                )
                return
        else:
            queries = list(MAJOR_TEAMS)

        # 팀당 요청 1~2개, 요청 간격 2초 → 예상 시간 안내
        per_team = 2.5 if 대상.value == "saved" else 5
        eta = max(1, round(len(queries) * per_team / 60))
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⏳ 전체 팀 갱신 시작",
                description=f"{대상.name}: **{len(queries)}팀**\n예상 소요: 약 {eta}분\n사이트 보호를 위해 한 팀씩 천천히 가져옵니다.",
                color=COLOR_INFO,
            ),
            ephemeral=True,
        )

        started = time.monotonic()
        last_edit = 0.0

        async def progress(done: int, total: int, current: str) -> None:
            nonlocal last_edit
            # Discord 수정 요청이 너무 잦지 않게 10초마다 + 마지막에만
            if done != total and time.monotonic() - last_edit < 10:
                return
            last_edit = time.monotonic()
            bar = "█" * int(done / total * 20) + "░" * (20 - int(done / total * 20))
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="⏳ 전체 팀 갱신 중",
                    description=f"`{bar}` {done}/{total}\n최근: {current}",
                    color=COLOR_INFO,
                )
            )

        async def run() -> None:
            try:
                result = await team_service.refresh_many(queries, progress)
            except Exception as exc:
                log.exception("전체 팀 갱신 실패")
                await _safe_edit(interaction, error_embed(f"전체 갱신 중 오류: {exc}"))
                return
            minutes = (time.monotonic() - started) / 60
            embed = discord.Embed(
                title="✅ 전체 팀 갱신 완료",
                description=f"성공 **{len(result.ok)}팀** · 실패 **{len(result.failed)}팀** · {minutes:.1f}분",
                color=COLOR_OK,
            )
            if result.failed:
                lines = [f"`{q}` — {why}" for q, why in result.failed[:15]]
                if len(result.failed) > 15:
                    lines.append(f"… 외 {len(result.failed) - 15}팀")
                embed.add_field(name="실패한 팀", value="\n".join(lines)[:1024], inline=False)
            await _safe_edit(interaction, embed)

        task = asyncio.create_task(run())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    @app_commands.command(name="선수갱신", description="ProSettings에서 선수 설정을 다시 가져옵니다 (12시간 캐시 무시).")
    @app_commands.describe(닉네임="선수 닉네임 (예: stax)")
    @app_commands.checks.cooldown(1, 10)
    async def refresh_player(self, interaction: discord.Interaction, 닉네임: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_player(interaction, 닉네임, force=True)

    @app_commands.command(name="선수설정등록", description="선수의 감도·장비·크로스헤어를 직접 입력합니다 (입력한 항목만 바뀜).")
    @app_commands.describe(
        닉네임="선수 닉네임 (이미 저장된 선수여야 해요)", dpi="마우스 DPI", 감도="게임 내 감도",
        스코프감도="스코프(줌) 감도", 폴링레이트="폴링레이트 Hz (예: 1000)", 해상도="예: 1920x1080",
        비율="화면 비율 (예: 16:9)", 마우스="마우스 이름", 키보드="키보드 이름", 마우스패드="마우스패드 이름",
        모니터="모니터 이름", 헤드셋="헤드셋 이름", 크로스헤어코드="게임 내 크로스헤어 가져오기 코드",
    )
    async def register_player_settings(
        self, interaction: discord.Interaction, 닉네임: str,
        dpi: app_commands.Range[int, 100, 20000] | None = None,
        감도: app_commands.Range[float, 0.01, 10] | None = None,
        스코프감도: app_commands.Range[float, 0.01, 10] | None = None,
        폴링레이트: app_commands.Range[int, 125, 8000] | None = None,
        해상도: str | None = None, 비율: str | None = None,
        마우스: str | None = None, 키보드: str | None = None, 마우스패드: str | None = None,
        모니터: str | None = None, 헤드셋: str | None = None, 크로스헤어코드: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        values = {k: v for k, v in {
            "dpi": dpi, "sensitivity": 감도, "scoped_sensitivity": 스코프감도, "polling_rate": 폴링레이트,
            "resolution": 해상도, "aspect_ratio": 비율,
        }.items() if v is not None}
        gear = {k: v.strip() for k, v in {
            "mouse": 마우스, "keyboard": 키보드, "mousepad": 마우스패드, "monitor": 모니터, "headset": 헤드셋,
        }.items() if v and v.strip()}
        code = 크로스헤어코드.strip() if 크로스헤어코드 and 크로스헤어코드.strip() else None
        if not (values or gear or code):
            await interaction.followup.send(embed=error_embed("입력한 항목이 없습니다. 바꿀 값을 하나 이상 넣어주세요."))
            return
        async with db.session() as s:
            lookup = await repo.find_player(s, 닉네임)
            if lookup.player is None:
                names = ", ".join(f"`{p.nickname}`" for p in lookup.candidates)
                msg = f"'{닉네임}' 선수를 찾을 수 없습니다." + (f"\n혹시 이 선수인가요? {names}" if names else "")
                await interaction.followup.send(embed=error_embed(msg))
                return
            await repo.save_manual_player_settings(s, lookup.player.id, values=values, gear=gear, crosshair_code=code)
            await s.commit()
            nickname = lookup.player.nickname
        await interaction.followup.send(embed=discord.Embed(
            title="✅ 선수 설정 저장",
            description=f"**{nickname}** 선수 설정을 저장했습니다. `/선수 {nickname}` 으로 확인해보세요.\n"
                        "직접 입력한 설정은 자동으로 덮어쓰지 않습니다.",
            color=COLOR_OK,
        ))

    @app_commands.command(name="경기갱신", description="VLR.gg에서 진행 중·예정 경기와 최근 결과를 다시 가져옵니다.")
    @app_commands.checks.cooldown(1, 30)
    async def refresh_matches(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            count = await match_service.refresh_matches()
        except (ScrapeError, ParseError) as exc:
            await interaction.followup.send(embed=error_embed(f"경기 정보를 가져오지 못했습니다.\n`{exc}`"))
            return
        await interaction.followup.send(
            embed=discord.Embed(title="✅ 경기 갱신 완료", description=f"경기 {count}개를 저장했습니다.", color=COLOR_OK)
        )

    @app_commands.command(name="상태", description="봇·DB·데이터 수집 상태를 확인합니다.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="🛠️ 봇 상태", color=COLOR_INFO)
        embed.add_field(name="Discord", value=f"{round(self.bot.latency * 1000)}ms · 서버 {len(self.bot.guilds)}곳")
        embed.add_field(name="가동 시간", value=_uptime(time.time() - self.started_at))
        if bridge.enabled:
            worker = f"🟢 켜짐 ({bridge.worker_name}) · 처리 {bridge.completed}건" if bridge.online else "💤 꺼짐"
            embed.add_field(name="PC 수집기", value=worker)

        if not db.configured:
            embed.add_field(name="DB", value="⚪ 설정 안 됨", inline=False)
            await interaction.followup.send(embed=embed)
            return

        db_ms = await db.ping()
        if db_ms is None:
            embed.add_field(name="DB", value=f"🔴 연결 실패\n`{db.last_error}`", inline=False)
            await interaction.followup.send(embed=embed)
            return

        async with db.session() as s:
            revision = await repo.get_schema_revision(s)
            counts = await repo.get_table_counts(s)
            runs = await repo.get_last_scrape_runs(s, limit=6)

        embed.add_field(name="DB", value=f"🟢 {db_ms:.0f}ms · 스키마 `{revision}`")
        embed.add_field(
            name="저장된 데이터",
            value="\n".join(f"{k}: **{v}**" for k, v in counts.items()),
            inline=False,
        )
        if runs:
            icon = {"success": "🟢", "failed": "🔴", "running": "🟡"}
            lines = [
                f"{icon.get(r.status, '⚪')} `{r.source}/{r.job}`"
                f"{' ' + r.target if r.target else ''} · {ts(r.started_at, 'R')}"
                f"{' · ' + str(r.items) + '개' if r.status == 'success' else ''}"
                for r in runs
            ]
            embed.add_field(name="최근 수집", value="\n".join(lines)[:1024], inline=False)
        await interaction.followup.send(embed=embed)


_background_tasks: set[asyncio.Task[None]] = set()


async def _safe_edit(interaction: discord.Interaction, embed: discord.Embed) -> None:
    """응답 수정 (토큰 유효시간 15분이 지나 실패하면 로그만 남김)."""
    try:
        await interaction.edit_original_response(embed=embed)
    except discord.HTTPException:
        log.info("결과 메시지를 수정하지 못했습니다 (15분 경과 등). 결과는 /관리 상태 에서 확인 가능")


def _uptime(seconds: float) -> str:
    m, _ = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    return f"{d}일 {h}시간 {m}분" if d else f"{h}시간 {m}분"


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(AdminGroup(bot))
