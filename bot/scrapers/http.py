"""스크래퍼 공용 HTTP 클라이언트.

외부 사이트에 부담을 주지 않기 위한 규칙을 한곳에서 강제한다.
- 봇임을 밝히는 User-Agent
- 호스트별 최소 요청 간격 (기본 2초) — 동시에 여러 작업이 돌아도 순서대로 보냄
- 타임아웃, 재시도(429/5xx/네트워크 오류), 지수 백오프 + 지터, Retry-After 준수
- robots.txt 확인 (금지된 경로는 요청하지 않음)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp

log = logging.getLogger("valobot.http")

USER_AGENT = (
    "Mozilla/5.0 (compatible; ValoProBot/0.3; "
    "+https://github.com/galam0/valorant-pro-discord-bot)"
)
ROBOTS_UA = "ValoProBot"


class ScrapeError(Exception):
    """요청이 최종적으로 실패했을 때 (재시도 소진, 404, robots 금지 등)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class HttpClient:
    def __init__(
        self,
        *,
        min_interval: float = 2.0,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ) -> None:
        self.min_interval = min_interval
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._session: aiohttp.ClientSession | None = None
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.8",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # -- 예의 지키기 ---------------------------------------------------------

    async def _wait_turn(self, host: str) -> None:
        """같은 호스트에 대한 요청 사이에 min_interval 이상 간격을 둔다 (lock을 잡은 상태에서 호출)."""
        last = self._host_last.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)

    async def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                text = await self._fetch_raw(f"{base}/robots.txt", check_robots=False, retries=1)
                parser.parse(text.splitlines())
            except ScrapeError as exc:
                if exc.status in (401, 403):
                    log.warning("%s robots.txt 접근 거부 → 모든 요청을 보류합니다.", base)
                    parser = RobotFileParser()
                    parser.parse(["User-agent: *", "Disallow: /"])
                else:
                    # robots.txt가 없거나 일시 오류 → 표준에 따라 허용으로 간주
                    parser = None
            self._robots[base] = parser
        parser = self._robots[base]
        return True if parser is None else parser.can_fetch(ROBOTS_UA, url)

    # -- 요청 ---------------------------------------------------------------

    async def get_text(self, url: str) -> str:
        t0 = time.monotonic()
        try:
            return await self._fetch_raw(url, check_robots=True, retries=self.max_retries)
        finally:
            # 대기 시간(같은 사이트 2초 간격 + 다른 작업 순번) 포함. 느린 명령어를 찾을 때 '[성능]'으로 검색
            log.info("[성능] 요청 %s %.1f초", url, time.monotonic() - t0)

    async def _fetch_raw(self, url: str, *, check_robots: bool, retries: int) -> str:
        if check_robots and not await self._allowed_by_robots(url):
            raise ScrapeError(f"robots.txt가 허용하지 않는 주소입니다: {url}")

        host = urlsplit(url).netloc
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        session = await self._get_session()
        last_error: str = ""
        last_status: int | None = None

        for attempt in range(1, retries + 1):
            retry_after: float | None = None
            async with lock:
                await self._wait_turn(host)
                try:
                    async with session.get(url) as resp:
                        self._host_last[host] = time.monotonic()
                        last_status = resp.status
                        if resp.status == 200:
                            return await resp.text()
                        if resp.status == 404:
                            raise ScrapeError(f"페이지 없음 (404): {url}", status=404)
                        if resp.status in (401, 403):
                            raise ScrapeError(f"접근 거부 ({resp.status}): {url}", status=resp.status)
                        last_error = f"HTTP {resp.status}"
                        if resp.status == 429:
                            ra = resp.headers.get("Retry-After", "")
                            retry_after = float(ra) if ra.isdigit() else None
                        elif resp.status < 500:
                            raise ScrapeError(f"요청 실패 ({resp.status}): {url}", status=resp.status)
                except ScrapeError:
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    self._host_last[host] = time.monotonic()
                    last_error = f"{type(exc).__name__}: {exc}"

            if attempt < retries:
                delay = retry_after or self.backoff_base ** attempt + random.uniform(0, 1)
                delay = min(delay, 120)
                log.warning("요청 실패 (%s), %.1f초 후 재시도 %d/%d: %s", last_error, delay, attempt, retries - 1, url)
                await asyncio.sleep(delay)

        raise ScrapeError(f"재시도 후에도 실패 ({last_error}): {url}", status=last_status)


# 앱 전체에서 공유 (호스트별 간격 제한이 모든 스크래퍼에 함께 적용되도록)
http_client = HttpClient()
