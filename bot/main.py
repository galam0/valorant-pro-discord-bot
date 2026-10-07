"""VALORANT 프로팀 정보 Discord Bot 진입점 (Phase 1).

실행: python -m bot.main
"""

from __future__ import annotations

import logging
import os
import sys
import time

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 설정 / 로깅 (Phase 2 이후 bot/utils/config.py, logger.py 로 분리 예정)
# ---------------------------------------------------------------------------

load_dotenv()

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
# discord.py 내부 로그는 너무 시끄러우므로 한 단계 낮춤
logging.getLogger("discord").setLevel(logging.WARNING)
logger = logging.getLogger("valobot")


def _parse_guild_id(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("DEV_GUILD_ID 값이 숫자가 아닙니다: %r (무시함)", raw)
        return None


DISCORD_TOKEN: str | None = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID: int | None = _parse_guild_id(os.getenv("DEV_GUILD_ID"))

# Render Web Service는 PORT 환경변수를 주입하고, 그 포트가 열려 있어야 배포가 성공한다.
# 로컬에서는 PORT가 없으므로 헬스체크 서버를 띄우지 않는다.
HEALTH_PORT: int | None = int(os.environ["PORT"]) if os.getenv("PORT", "").isdigit() else None

EMBED_COLOR = discord.Color.from_rgb(255, 70, 85)  # VALORANT 레드


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


class ValorantBot(commands.Bot):
    def __init__(self) -> None:
        # Slash Command만 사용하므로 message_content 같은 특권 인텐트는 필요 없음
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.started_at: float = time.time()
        self._health_runner: web.AppRunner | None = None

    # -- 헬스체크 HTTP 서버 -------------------------------------------------
    # Render 무료 Web Service는 15분간 요청이 없으면 잠들기 때문에,
    # UptimeRobot 같은 외부 모니터가 /health 를 주기적으로 호출해 깨워둔다.
    # aiohttp는 discord.py 의존성이라 추가 설치가 필요 없다.

    async def _health(self, _request: web.Request) -> web.Response:
        ready = self.is_ready()
        body = {
            "status": "ok" if ready else "starting",
            "discord_ready": ready,
            "latency_ms": round(self.latency * 1000) if ready else None,
            "uptime_s": int(time.time() - self.started_at),
        }
        # 봇이 아직 로그인 중이어도 200을 반환해 Render 배포가 실패하지 않게 한다.
        return web.json_response(body)

    async def _start_health_server(self, port: int) -> None:
        app = web.Application()
        app.router.add_get("/", self._health)
        app.router.add_get("/health", self._health)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, host="0.0.0.0", port=port).start()
        self._health_runner = runner
        logger.info("헬스체크 서버 시작: 0.0.0.0:%d/health", port)

    async def close(self) -> None:
        if self._health_runner is not None:
            await self._health_runner.cleanup()
        await super().close()

    # -- 라이프사이클 --------------------------------------------------------

    async def setup_hook(self) -> None:
        """봇 로그인 직후 1회 실행. 헬스 서버를 띄우고 Slash Command를 동기화한다."""
        if HEALTH_PORT:
            await self._start_health_server(HEALTH_PORT)

        register_commands(self.tree)

        if DEV_GUILD_ID:
            # 개발 서버에만 즉시 동기화 (반영까지 수 초)
            guild = discord.Object(id=DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("개발 서버(%s)에 명령어 %d개 동기화 완료", DEV_GUILD_ID, len(synced))
        else:
            # 전역 동기화 (처음 반영까지 최대 1시간 걸릴 수 있음)
            synced = await self.tree.sync()
            logger.info("전역 명령어 %d개 동기화 완료", len(synced))

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info("로그인: %s (ID: %s) / 서버 %d곳", self.user, self.user.id, len(self.guilds))
        await self.change_presence(activity=discord.Game(name="/팀 · /선수 · /ping"))


# ---------------------------------------------------------------------------
# 명령어 (Phase 5에서 bot/commands/ 로 Cog 분리 예정)
# ---------------------------------------------------------------------------


def register_commands(tree: app_commands.CommandTree) -> None:
    @tree.command(name="ping", description="봇 응답 속도를 확인합니다.")
    async def ping(interaction: discord.Interaction) -> None:
        latency_ms = round(interaction.client.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"응답 속도: **{latency_ms}ms**",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed)

    @tree.command(name="팀", description="VALORANT 프로팀 정보를 조회합니다.")
    @app_commands.describe(이름="팀 이름 (예: T1, 젠지, DRX)")
    async def team(interaction: discord.Interaction, 이름: str) -> None:
        embed = discord.Embed(
            title=f"🔍 {이름}",
            description="팀 정보 기능은 준비 중입니다. (Phase 3에서 구현 예정)",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="선수", description="VALORANT 프로 선수 설정을 조회합니다.")
    @app_commands.describe(닉네임="선수 닉네임 (예: stax, t3xture)")
    async def player(interaction: discord.Interaction, 닉네임: str) -> None:
        embed = discord.Embed(
            title=f"🔍 {닉네임}",
            description="선수 정보 기능은 준비 중입니다. (Phase 4에서 구현 예정)",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """모든 Slash Command 오류를 잡아 봇이 죽지 않게 하고 사용자에게 한국어로 안내."""
        logger.exception("명령어 처리 중 오류 (/%s)", getattr(interaction.command, "name", "?"), exc_info=error)
        message = "⚠️ 명령어를 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.warning("오류 메시지 전송 실패")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN 환경변수가 없습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    bot = ValorantBot()
    try:
        # log_handler=None: 위에서 설정한 logging 설정을 그대로 사용
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.critical("Discord 로그인 실패: 토큰이 올바르지 않습니다.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        logger.critical("Developer Portal에서 필요한 Privileged Intent가 꺼져 있습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
