"""Alembic 실행 환경 (async SQLAlchemy).

- `alembic upgrade head` (CLI) 와 봇 시작 시 자동 마이그레이션(bot/database/migrate.py) 둘 다 이 파일을 쓴다.
- DB 주소는 DATABASE_URL 환경변수(또는 config.attributes["database_url"])에서 읽는다.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from bot.database.database import build_async_url, create_engine_from_url
from bot.database.models import Base
from bot.utils.config import settings

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url") or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL 환경변수가 없습니다.")
    return url


def run_migrations_offline() -> None:
    """DB에 접속하지 않고 SQL만 출력 (alembic upgrade head --sql)."""
    url, _ = build_async_url(_database_url())
    context.configure(
        url=url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine_from_url(_database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
