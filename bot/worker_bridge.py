"""PC 수집기 연결 (봇 쪽).

일부 사이트(ProSettings)가 Render 같은 데이터센터 IP를 막기 때문에,
그 사이트의 페이지 요청만 사용자의 PC에서 실행되는 수집기(bot/local_worker.py)에 맡긴다.

동작
1) 봇이 '이 주소를 가져와 줘' 작업을 대기열에 넣고 결과를 기다린다 (fetch).
2) PC 수집기는 GET /worker/next 로 작업을 받아간다 (롱폴링: 최대 25초 대기 후 빈 응답).
3) PC가 페이지를 받아 POST /worker/result 로 HTML을 돌려주면, 기다리던 fetch가 끝난다.

- PC는 DB에 접근하지 않는다 (DB 비밀번호 불필요, Neon 컴퓨트 시간도 쓰지 않음).
- WORKER_TOKEN 이 같아야만 작업을 주고받는다. 설정하지 않으면 이 기능은 꺼진다.
- 허용된 사이트(ALLOWED_HOSTS)의 주소만 맡긴다. PC 수집기도 같은 목록으로 다시 검사한다.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from aiohttp import web

from bot.scrapers.http import ScrapeError
from bot.utils.config import settings

log = logging.getLogger("valobot.worker")

ALLOWED_HOSTS = {"prosettings.net", "www.prosettings.net"}
ONLINE_WINDOW = 60  # 마지막 접속이 60초 이내면 '켜져 있음'


class WorkerUnavailable(ScrapeError):
    """PC 수집기가 꺼져 있거나 제시간에 응답하지 않음."""


@dataclass
class FetchResult:
    status: int          # HTTP 상태 (0 = 네트워크 오류)
    html: str | None
    error: str | None


class WorkerBridge:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self._waiting: dict[str, asyncio.Future[FetchResult]] = {}
        self.last_seen: float = 0.0
        self.worker_name: str | None = None
        self.completed = 0

    @property
    def enabled(self) -> bool:
        return bool(settings.worker_token)

    @property
    def online(self) -> bool:
        return self.enabled and time.time() - self.last_seen < ONLINE_WINDOW

    # -- 봇 쪽 사용 ---------------------------------------------------------

    async def fetch(self, url: str, timeout: float = 30.0) -> FetchResult:
        if urlsplit(url).hostname not in ALLOWED_HOSTS:
            raise ValueError(f"PC 수집기에 맡길 수 없는 주소입니다: {url}")
        if not self.online:
            raise WorkerUnavailable("수집 PC가 꺼져 있습니다.")

        job_id = uuid.uuid4().hex
        future: asyncio.Future[FetchResult] = asyncio.get_running_loop().create_future()
        self._waiting[job_id] = future
        await self._queue.put({"id": job_id, "url": url, "queued_at": str(time.time())})
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise WorkerUnavailable("수집 PC가 제시간에 응답하지 않았습니다.") from None
        finally:
            self._waiting.pop(job_id, None)

    # -- HTTP 엔드포인트 (PC 수집기용) ----------------------------------------

    def _authorized(self, request: web.Request) -> bool:
        if not self.enabled:
            return False
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip()
        return hmac.compare_digest(token.encode(), (settings.worker_token or "").encode())

    async def handle_next(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            raise web.HTTPNotFound()
        self.last_seen = time.time()
        self.worker_name = request.headers.get("X-Worker-Name", "PC")[:50]
        deadline = time.monotonic() + 25
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return web.Response(status=204)
            try:
                job = await asyncio.wait_for(self._queue.get(), remaining)
            except asyncio.TimeoutError:
                return web.Response(status=204)
            finally:
                self.last_seen = time.time()
            # 기다리던 쪽이 이미 시간 초과로 포기한 작업은 건너뛴다
            if job["id"] in self._waiting:
                return web.json_response({"id": job["id"], "url": job["url"]})

    async def handle_result(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            raise web.HTTPNotFound()
        self.last_seen = time.time()
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest() from None
        future = self._waiting.get(str(body.get("id")))
        if future is not None and not future.done():
            future.set_result(FetchResult(
                status=int(body.get("status") or 0),
                html=body.get("html"),
                error=body.get("error"),
            ))
            self.completed += 1
        return web.json_response({"ok": True})

    def register(self, app: web.Application) -> None:
        app.router.add_get("/worker/next", self.handle_next)
        app.router.add_post("/worker/result", self.handle_result)


bridge = WorkerBridge()
