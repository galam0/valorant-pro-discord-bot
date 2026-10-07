"""봇 시작 시 Alembic 마이그레이션을 코드로 실행한다.

Render 무료 플랜에는 배포 전 명령(pre-deploy)이 없으므로, 시작할 때 `upgrade head`를 적용한다.
이미 최신이면 아무 일도 하지 않는다. 실패해도 봇은 계속 실행되고 DB 기능만 꺼진다.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

log = logging.getLogger("valobot.db.migrate")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # URL을 ini 옵션에 넣으면 비밀번호의 % 문자가 문제를 일으키므로 attributes로 전달
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade_sync(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


async def upgrade_to_head(database_url: str) -> None:
    """별도 스레드에서 실행 (migrations/env.py가 자체 이벤트 루프를 돌리기 때문)."""
    log.info("DB 마이그레이션 확인 중...")
    await asyncio.to_thread(_upgrade_sync, database_url)
    log.info("DB 마이그레이션 완료 (최신 스키마)")
