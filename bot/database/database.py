"""PostgreSQL 연결 (SQLAlchemy 2.0 async + asyncpg).

discord.py가 asyncio 기반이므로 DB 접근도 비동기로 해서 봇이 멈추지 않게 한다.

Neon 대응
- Neon/Render가 주는 URL(postgresql://...?sslmode=require&channel_binding=require)을
  asyncpg용(postgresql+asyncpg://)으로 바꾸고, asyncpg가 모르는 쿼리 파라미터는 제거한 뒤
  SSL은 connect_args로 넘긴다.
- '-pooler' 주소(PgBouncer)를 쓰면 asyncpg의 prepared statement 캐시가 충돌할 수 있어 끈다.
- Neon 무료 플랜은 5분 동안 쿼리가 없으면 일시정지되어 기존 연결이 끊긴다.
  pool_pre_ping / pool_recycle 로 끊긴 연결을 자동으로 다시 맺는다.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

log = logging.getLogger("valobot.db")

_SSL_REQUIRED_MODES = {"require", "verify-ca", "verify-full"}
# asyncpg.connect()가 받지 않는 libpq 전용 파라미터
_LIBPQ_ONLY_PARAMS = ("sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "options")


def build_async_url(raw_url: str) -> tuple[URL, dict[str, Any]]:
    """DATABASE_URL → (asyncpg용 URL, connect_args)."""
    url = make_url(raw_url.strip())

    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}:
        url = url.set(drivername="postgresql+asyncpg")
    elif url.drivername != "postgresql+asyncpg":
        raise ValueError(f"PostgreSQL URL이 아닙니다: {url.drivername}")

    sslmode = str(url.query.get("sslmode", "")).lower()
    host = url.host or ""
    url = url.difference_update_query(_LIBPQ_ONLY_PARAMS)

    connect_args: dict[str, Any] = {
        "timeout": 20,          # 연결 시도 제한 (Neon 콜드 스타트는 보통 1~3초)
        "command_timeout": 30,  # 쿼리 1개 제한
    }
    if sslmode in _SSL_REQUIRED_MODES or host.endswith(".neon.tech"):
        connect_args["ssl"] = "require"

    if "-pooler" in host:
        # PgBouncer(transaction 모드)에서는 같은 이름의 prepared statement가 충돌할 수 있음
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4()}__"
        url = url.update_query_dict({"prepared_statement_cache_size": "0"})

    return url, connect_args


def create_engine_from_url(raw_url: str, **engine_kwargs: Any) -> AsyncEngine:
    url, connect_args = build_async_url(raw_url)
    kwargs: dict[str, Any] = {
        "pool_size": 5,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_recycle": 280,  # Neon 자동 일시정지(5분)보다 짧게
        "connect_args": connect_args,
    }
    kwargs.update(engine_kwargs)
    if "poolclass" in engine_kwargs:
        # NullPool 등은 pool_size/max_overflow를 받지 않는다 (마이그레이션용)
        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
    return create_async_engine(url, **kwargs)


class Database:
    """앱 전체에서 하나만 쓰는 DB 핸들."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self.last_ok_at: float | None = None
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return self.engine is not None

    def configure(self, raw_url: str) -> None:
        self.engine = create_engine_from_url(raw_url)
        self._sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        url = self.engine.url
        # 비밀번호는 절대 로그에 남기지 않는다
        log.info("DB 설정 완료: %s@%s/%s", url.username, url.host, url.database)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """`async with db.session() as s:` — 예외가 나면 자동 롤백."""
        if self._sessionmaker is None:
            raise RuntimeError("DB가 설정되지 않았습니다 (DATABASE_URL 확인).")
        async with self._sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> float | None:
        """DB 왕복 시간(ms). 실패하면 None. 예외를 밖으로 던지지 않는다."""
        if self.engine is None:
            return None
        started = time.perf_counter()
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # 네트워크/인증/일시정지 등 모든 실패
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("DB 연결 확인 실패: %s", self.last_error)
            return None
        self.last_ok_at = time.time()
        self.last_error = None
        return (time.perf_counter() - started) * 1000

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


db = Database()
