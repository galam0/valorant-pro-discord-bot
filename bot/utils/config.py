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
    # 시작할 때 Alembic 마이그레이션을 자동 적용할지 (기본 켬)
    auto_migrate: bool = field(
        default_factory=lambda: os.getenv("AUTO_MIGRATE", "1").strip().lower() not in {"0", "false", "no"}
    )


settings = Settings()
