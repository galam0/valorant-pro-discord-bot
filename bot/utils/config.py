"""환경변수 기반 설정.

모든 설정은 여기서만 읽는다. 다른 모듈은 `from bot.utils.config import settings` 로 사용.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

_log = logging.getLogger("valobot.config")


def _int_or_none(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        _log.warning("%s 값이 숫자가 아닙니다: %r (무시함)", name, raw)
        return None


def _int_set(name: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in os.getenv(name, "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            ids.add(int(part))
        else:
            _log.warning("%s 에 숫자가 아닌 값이 있습니다: %r (무시함)", name, part)
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    discord_token: str | None = field(default_factory=lambda: os.getenv("DISCORD_TOKEN") or None)
    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL") or None)
    dev_guild_id: int | None = field(default_factory=lambda: _int_or_none("DEV_GUILD_ID"))
    admin_user_ids: frozenset[int] = field(default_factory=lambda: _int_set("ADMIN_USER_IDS"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    # Render가 주입. 있으면 /health 서버를 띄운다.
    port: int | None = field(default_factory=lambda: _int_or_none("PORT"))
    # ProSettings 사용 여부 (기본 꺼짐: 사이트 허가를 받기 전에는 요청하지 않는다)
    prosettings_enabled: bool = field(
        default_factory=lambda: os.getenv("PROSETTINGS_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    )
    # PC 수집기와 봇이 공유하는 비밀값 (설정하면 ProSettings 요청을 PC 수집기에 맡김)
    worker_token: str | None = field(default_factory=lambda: os.getenv("WORKER_TOKEN") or None)
    # PC 수집기가 접속할 봇 주소 (PC 쪽 .env 에서만 사용)
    bot_url: str | None = field(default_factory=lambda: (os.getenv("BOT_URL") or "").rstrip("/") or None)
    # /선수 명령어 공개 여부 (기본 꺼짐: ProSettings 허가 전까지 일반 사용자에게는 "준비 중" 안내)
    player_command_enabled: bool = field(
        default_factory=lambda: os.getenv("PLAYER_COMMAND_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    )
    # 시작할 때 Alembic 마이그레이션을 자동 적용할지 (기본 켬)
    auto_migrate: bool = field(
        default_factory=lambda: os.getenv("AUTO_MIGRATE", "1").strip().lower() not in {"0", "false", "no"}
    )


settings = Settings()
