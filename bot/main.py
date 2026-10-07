"""VALORANT 프로팀 정보 Discord Bot 진입점.

실행: python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

import discord
from aiohttp import web
from discord.ext import commands

from bot.commands import EXTENSIONS, install_error_handler
from bot.database.database import db
from bot.render import images as card_images
from bot.scrapers.http import http_client
from bot.utils.config import settings
from bot.utils.logger import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger("valobot")

# Discord(Cloudflare) 429 차단 시 재시도 대기 시간 (초)
RETRY_BASE_DELAY = 60
RETRY_MAX_DELAY = 30 * 60


# ---------------------------------------------------------------------------
# 헬스체크 HTTP 서버
# ---------------------------------------------------------------------------
# Discord 로그인과 무관하게 프로세스 시작 직후 띄운다.
#  - Render는 포트가 열려야 배포 성공으로 판단한다.
#  - 로그인이 429로 막혀 재시도 대기 중이어도 프로세스가 살아 있어야 한다.
#  - UptimeRobot이 /health 를 5분마다 호출해 무료 인스턴스가 잠들지 않게 한다.
#
# 주의: /health 에서 DB에 쿼리하지 않는다.
#   5분마다 DB를 깨우면 Neon 무료 플랜이 일시정지되지 못해 월 컴퓨트 한도(100 CU-h)를 넘는다.
#   DB 상태는 마지막으로 확인된 결과만 보여준다.


class HealthServer:
    def __init__(self) -> None:
        self.started_at: float = time.time()
        self.bot: ValorantBot | None = None
        self.state: str = "starting"  # starting | ok | rate_limited
        self.next_retry_at: float | None = None
        self._runner: web.AppRunner | None = None

    async def _handle(self, _request: web.Request) -> web.Response:
        ready = self.bot is not None and self.bot.is_ready()
        if not db.configured:
            db_state = "not_configured"
        elif db.last_error:
            db_state = "error"
        elif db.last_ok_at:
            db_state = "ok"
        else:
            db_state = "unknown"
        body = {
            "status": "ok" if ready else self.state,
            "discord_ready": ready,
            "latency_ms": round(self.bot.latency * 1000) if ready and self.bot else None,
            "database": db_state,
            "uptime_s": int(time.time() - self.started_at),
            "next_retry_in_s": (
                max(0, int(self.next_retry_at - time.time())) if self.next_retry_at else None
            ),
        }
        # 항상 200: 로그인 재시도 중에도 Render가 서비스를 내리지 않게 한다.
        return web.json_response(body)

    async def start(self, port: int) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle)
        app.router.add_get("/health", self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host="0.0.0.0", port=port).start()
        logger.info("헬스체크 서버 시작: 0.0.0.0:%d/health", port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


# ---------------------------------------------------------------------------
# DB 초기화
# ---------------------------------------------------------------------------


async def init_database() -> None:
    """DB 연결 + 마이그레이션. 실패해도 예외를 던지지 않는다 (봇은 DB 없이도 켜져야 함)."""
    if not settings.database_url:
        logger.warning("DATABASE_URL이 없습니다. DB 기능 없이 실행합니다.")
        return

    try:
        db.configure(settings.database_url)
    except Exception:
        logger.exception("DATABASE_URL 형식이 올바르지 않습니다. DB 기능 없이 실행합니다.")
        return

    if settings.auto_migrate:
        try:
            # 순환 import 및 alembic 로딩 비용을 피하기 위해 필요할 때만 import
            from bot.database.migrate import upgrade_to_head

            await upgrade_to_head(settings.database_url)
        except Exception as exc:
            db.last_error = f"마이그레이션 실패: {type(exc).__name__}: {exc}"
            logger.exception("DB 마이그레이션 실패 (봇은 계속 실행)")
            return

    ms = await db.ping()
    if ms is not None:
        logger.info("DB 연결 확인 (%.0fms)", ms)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


class ValorantBot(commands.Bot):
    def __init__(self) -> None:
        # Slash Command만 사용하므로 message_content 같은 특권 인텐트는 필요 없음
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self) -> None:
        """로그인 직후 1회 실행. 명령어(Cog)를 불러오고 Discord에 동기화한다."""
        install_error_handler(self.tree)
        for ext in EXTENSIONS:
            await self.load_extension(ext)

        if settings.dev_guild_id:
            # 개발 서버에만 즉시 동기화 (반영까지 수 초)
            guild = discord.Object(id=settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("개발 서버(%s)에 명령어 %d개 동기화 완료", settings.dev_guild_id, len(synced))
        else:
            # 전역 동기화 (처음 반영까지 최대 1시간 걸릴 수 있음)
            synced = await self.tree.sync()
            logger.info("전역 명령어 %d개 동기화 완료", len(synced))

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info("로그인: %s (ID: %s) / 서버 %d곳", self.user, self.user.id, len(self.guilds))
        await self.change_presence(activity=discord.Game(name="/팀 · /경기 · /선수"))


# ---------------------------------------------------------------------------
# 실행 루프 (429 차단 시 프로세스를 죽이지 않고 지수 백오프로 재시도)
# ---------------------------------------------------------------------------


def _is_cloudflare_ban(exc: discord.HTTPException) -> bool:
    text = str(exc)
    return exc.status == 429 and ("cloudflare" in text.lower() or "1015" in text)


async def run_forever(token: str, health: HealthServer | None) -> None:
    delay = RETRY_BASE_DELAY
    while True:
        bot = ValorantBot()
        if health:
            health.bot = bot
            health.state = "starting"
            health.next_retry_at = None
        try:
            async with bot:
                await bot.start(token)
            return  # 정상 종료(close 호출)
        except discord.HTTPException as exc:
            if exc.status != 429:
                raise
            kind = "Cloudflare IP 차단(1015)" if _is_cloudflare_ban(exc) else "Discord 속도 제한"
            logger.warning("로그인 실패: %s. %d초 후 재시도합니다.", kind, delay)
            if health:
                health.state = "rate_limited"
                health.next_retry_at = time.time() + delay
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_DELAY)


async def amain(token: str) -> None:
    health: HealthServer | None = None
    if settings.port:
        health = HealthServer()
        await health.start(settings.port)
    try:
        await init_database()
        await run_forever(token, health)
    finally:
        await http_client.close()
        await card_images.close()
        await db.dispose()
        if health:
            await health.stop()


def main() -> None:
    if not settings.discord_token:
        logger.critical("DISCORD_TOKEN 환경변수가 없습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    try:
        asyncio.run(amain(settings.discord_token))
    except KeyboardInterrupt:
        logger.info("종료합니다.")
    except discord.LoginFailure:
        logger.critical("Discord 로그인 실패: 토큰이 올바르지 않습니다.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        logger.critical("Developer Portal에서 필요한 Privileged Intent가 꺼져 있습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
