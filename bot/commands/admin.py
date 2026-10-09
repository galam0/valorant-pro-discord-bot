"""/관리 — 관리자 전용 데이터 갱신·상태 확인.

권한: ADMIN_USER_IDS 에 있는 사용자, 또는 서버 관리자 권한(Administrator)이 있는 사용자.
"""

from __future__ import annotations

import asyncio
import io
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
from bot.services import economy_service as eco_service
from bot.services import emoji_service, match_service, team_service
from bot import scheduler
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
        감도: app_commands.Range[float, 0.01, 10.0] | None = None,
        스코프감도: app_commands.Range[float, 0.01, 10.0] | None = None,
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

    @app_commands.command(name="별칭추가", description="팀 검색 별칭을 추가합니다 (예: 젠지 → Gen.G).")
    @app_commands.describe(팀="별칭을 붙일 팀 (이름·기존 별칭·VLR ID)", 별칭="새 별칭 (한글·영문 모두 가능, 띄어쓰기·기호는 무시됨)")
    async def add_alias(self, interaction: discord.Interaction, 팀: str, 별칭: str) -> None:
        await interaction.response.defer(ephemeral=True)
        key = repo.normalize_key(별칭)
        if len(key) < 2:
            await interaction.followup.send(embed=error_embed("별칭은 기호·공백을 빼고 2글자 이상이어야 합니다."))
            return
        if len(key) > 40:
            await interaction.followup.send(embed=error_embed("별칭이 너무 깁니다 (40자 이하)."))
            return
        async with db.session() as s:
            lookup = await repo.find_team(s, 팀)
            if lookup.team is None:
                names = ", ".join(f"`{t.name}`" for t in lookup.candidates)
                msg = f"'{팀}' 팀을 하나로 특정하지 못했습니다." + (f"\n혹시 이 팀인가요? {names}" if names else "\n먼저 `/관리 팀갱신`으로 팀을 수집해주세요.")
                await interaction.followup.send(embed=error_embed(msg))
                return
            team = lookup.team
            owner = await repo.get_alias_owner(s, 별칭)
            if owner is not None:
                who = "이 팀" if owner[1].id == team.id else f"**{owner[1].name}**"
                await interaction.followup.send(embed=error_embed(f"'{별칭}' 별칭은 이미 {who}에서 사용 중입니다."))
                return
            await repo.add_team_alias(s, team.id, 별칭, source="manual")
            await s.commit()
            team_name = team.name
        await interaction.followup.send(embed=discord.Embed(
            title="✅ 별칭 추가", description=f"`{별칭}` → **{team_name}**\n이제 `/팀 {별칭}` 으로 검색할 수 있어요.", color=COLOR_OK))

    @app_commands.command(name="별칭삭제", description="직접 추가한 팀 별칭을 삭제합니다.")
    @app_commands.describe(별칭="삭제할 별칭")
    async def remove_alias(self, interaction: discord.Interaction, 별칭: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session() as s:
            owner = await repo.get_alias_owner(s, 별칭)
            if owner is None:
                await interaction.followup.send(embed=error_embed(f"'{별칭}' 별칭을 찾을 수 없습니다."))
                return
            if owner[0].source != "manual":
                await interaction.followup.send(embed=error_embed(
                    f"'{별칭}'은 팀 이름에서 자동으로 만들어진 별칭이라 삭제할 수 없습니다."))
                return
            await repo.remove_manual_alias(s, 별칭)
            await s.commit()
            team_name = owner[1].name
        await interaction.followup.send(embed=discord.Embed(
            title="🗑️ 별칭 삭제", description=f"`{별칭}` (**{team_name}**) 별칭을 삭제했습니다.", color=COLOR_OK))

    @app_commands.command(name="별칭목록", description="팀에 등록된 별칭을 확인합니다.")
    @app_commands.describe(팀="팀 이름 또는 별칭")
    async def list_aliases(self, interaction: discord.Interaction, 팀: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session() as s:
            lookup = await repo.find_team(s, 팀)
            if lookup.team is None:
                await interaction.followup.send(embed=error_embed(f"'{팀}' 팀을 찾을 수 없습니다."))
                return
            aliases = await repo.list_team_aliases(s, lookup.team.id)
            name = lookup.team.name
        manual = [a.alias for a in aliases if a.source == "manual"]
        auto = [a.alias for a in aliases if a.source != "manual"]
        embed = discord.Embed(title=f"🏷️ {name} 별칭", color=COLOR_INFO)
        embed.add_field(name="직접 추가 (삭제 가능)", value=", ".join(f"`{a}`" for a in manual) or "없음", inline=False)
        embed.add_field(name="자동 생성", value=", ".join(f"`{a}`" for a in auto)[:1000] or "없음", inline=False)
        embed.set_footer(text="별칭은 공백·기호·대소문자를 구분하지 않아 소문자로 저장됩니다")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="이모지생성", description="저장된 모든 팀 로고로 봇 전용 이모지를 만듭니다 (몇 분 걸림).")
    @app_commands.describe(덮어쓰기="이미 만든 팀 이모지도 지우고 다시 만들기 (로고가 바뀐 경우)")
    @app_commands.checks.cooldown(1, 60)
    async def make_emojis(self, interaction: discord.Interaction, 덮어쓰기: bool = False) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("DB가 연결되지 않았습니다."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⏳ 팀 이모지 만드는 중",
                description="팀당 약 1~2초 걸려요. 끝나면 이 메시지가 결과로 바뀝니다.",
                color=COLOR_INFO,
            ),
            ephemeral=True,
        )

        async def run() -> None:
            try:
                res = await emoji_service.create_team_emojis(self.bot, overwrite=덮어쓰기)
            except Exception as exc:
                log.exception("팀 이모지 생성 실패")
                await _safe_edit(interaction, error_embed(f"이모지 생성 중 오류: {exc}"))
                return
            embed = discord.Embed(
                title="✅ 팀 이모지 완료",
                description=(f"새로 만듦 **{len(res.created)}** · 이미 있음 **{len(res.existed)}** · "
                             f"로고 없음 **{len(res.skipped)}** · 실패 **{len(res.failed)}**"),
                color=COLOR_OK,
            )
            if res.failed:
                lines = [f"`{t}` — {why}" for t, why in res.failed[:10]]
                embed.add_field(name="실패한 팀", value="\n".join(lines)[:1024], inline=False)
            sample = " ".join(e for _, e in (res.created + res.existed)[:12])
            if sample:
                embed.add_field(name="미리보기", value=sample[:1024], inline=False)
            embed.set_footer(text="목록 파일의 `<:이름:번호>` 형식을 메시지에 쓰면 이모지로 보여요")
            lines = [f"{e}  {n}" for n, e in sorted(res.created + res.existed)]
            try:
                await interaction.edit_original_response(
                    embed=embed,
                    attachments=[discord.File(io.BytesIO("\n".join(lines).encode("utf-8")), filename="team_emojis.txt")] if lines else [],
                )
            except discord.HTTPException:
                log.info("이모지 결과 메시지를 수정하지 못했습니다 (15분 경과 등)")

        task = asyncio.create_task(run())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

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

        runs_next = scheduler.next_runs()
        if runs_next:
            names = {"matches": "경기 목록", "live": "진행 중 경기", "teams": "팀 정보"}
            embed.add_field(
                name="자동 갱신 (다음 실행)",
                value="\n".join(f"{names.get(k, k)} · {v}" for k, v in runs_next.items()),
                inline=False,
            )
        elif scheduler.enabled():
            embed.add_field(name="자동 갱신", value="⚪ 시작 안 됨", inline=False)

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


    @app_commands.command(name="vp현황", description="모든 서버의 VP 현황을 봅니다. (봇 제작자 전용)")
    async def vp_overview(self, interaction: discord.Interaction) -> None:
        if interaction.user.id not in settings.admin_user_ids:
            await interaction.response.send_message(embed=error_embed("봇 제작자(ADMIN_USER_IDS)만 볼 수 있어요."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        rows = await eco_service.all_guild_totals()
        embed = discord.Embed(title="💰 서버별 VP 현황", color=COLOR_INFO,
                              description=None if rows else "아직 지갑이 없어요.")
        for gid, users, total, top in rows[:8]:
            guild = self.bot.get_guild(gid)
            board = await eco_service.leaderboard(gid, 5)
            names = [await self._user_name(guild, uid) for uid, _ in board]
            top_lines = [f"`{i + 1}` {name} — {eco_service.fmt(bal)}" for i, (name, (_, bal)) in enumerate(zip(names, board))]
            embed.add_field(name=f"{guild.name if guild else gid} · 유저 {users}명 · 합계 {eco_service.fmt(total)}",
                            value="\n".join(top_lines) or "-", inline=False)
        if len(rows) > 8:
            embed.set_footer(text=f"서버 {len(rows)}곳 중 8곳만 보여줘요")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _user_name(self, guild: discord.Guild | None, uid: int) -> str:
        """서버 별명 → 캐시된 유저 → API 조회 순으로 이름을 찾는다 (못 찾으면 멘션 형태)."""
        member = guild.get_member(uid) if guild else None
        if member is not None:
            return f"{member.display_name} (`{uid}`)"
        user = self.bot.get_user(uid)
        if user is None:
            try:
                user = await self.bot.fetch_user(uid)
            except discord.HTTPException:
                return f"알 수 없음 (`{uid}`)"
        return f"{user.display_name} (`{uid}`)"

    @app_commands.command(name="vp지급", description="유저에게 VP를 지급하거나 회수합니다. (봇 제작자 전용)")
    @app_commands.describe(유저="대상 유저", 금액="지급할 VP (음수면 회수)")
    async def vp_grant(self, interaction: discord.Interaction, 유저: discord.Member, 금액: app_commands.Range[int, -1_000_000, 1_000_000]) -> None:
        if interaction.user.id not in settings.admin_user_ids:
            await interaction.response.send_message(embed=error_embed("봇 제작자(ADMIN_USER_IDS)만 사용할 수 있어요."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            bal = await eco_service.admin_grant(interaction.guild_id, 유저.id, 금액)
        except Exception as exc:
            await interaction.followup.send(embed=error_embed(f"처리하지 못했어요 (잔액 부족 등): {type(exc).__name__}"), ephemeral=True)
            return
        await interaction.followup.send(f"✅ {유저.mention} 에게 {금액:+,} VP · 현재 {eco_service.fmt(bal)}", ephemeral=True)


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
