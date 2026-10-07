"""PC 수집기 (사용자 PC에서 실행).

Render 봇이 직접 요청하면 차단되는 사이트(ProSettings)의 페이지를 대신 가져와서 봇에게 돌려준다.

실행 (프로젝트 폴더에서)
    python -m bot.local_worker

필요한 환경변수 (.env)
    BOT_URL=https://<Render 서비스 주소>.onrender.com
    WORKER_TOKEN=<Render 에 넣은 것과 같은 값>

- DB 비밀번호나 Discord 토큰은 필요 없다.
- 허용된 사이트(prosettings.net) 주소만 처리하고, robots.txt와 2초 요청 간격을 지킨다.
- 창을 닫거나 Ctrl+C 로 끄면 봇은 '수집 PC 꺼짐'으로 판단하고 저장된 정보를 보여준다.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from urllib.parse import urlsplit

import aiohttp

from bot.scrapers.http import USER_AGENT, HttpClient, ScrapeError
from bot.utils.config import settings
from bot.utils.logger import setup_logging
from bot.worker_bridge import ALLOWED_HOSTS

setup_logging(settings.log_level)
log = logging.getLogger("valobot.local_worker")


async def process(job: dict[str, str], client: HttpClient) -> dict[str, object]:
    url = job.get("url", "")
    if urlsplit(url).hostname not in ALLOWED_HOSTS:
        log.warning("허용되지 않은 주소라 거절: %s", url)
        return {"id": job["id"], "status": 0, "error": "허용되지 않은 주소"}
    try:
        html = await client.get_text(url)
        log.info("가져옴: %s (%d KB)", url, len(html) // 1024)
        return {"id": job["id"], "status": 200, "html": html}
    except ScrapeError as exc:
        log.warning("실패: %s → %s", url, exc)
        return {"id": job["id"], "status": exc.status or 0, "error": str(exc)}


async def run() -> None:
    if not settings.bot_url or not settings.worker_token:
        log.critical(".env 에 BOT_URL 과 WORKER_TOKEN 을 설정해주세요.")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {settings.worker_token}",
        "X-Worker-Name": socket.gethostname()[:50],
        "User-Agent": USER_AGENT + " local-worker",
    }
    client = HttpClient(min_interval=2.0)
    timeout = aiohttp.ClientTimeout(total=45)
    backoff = 5
    log.info("PC 수집기 시작 → %s (Ctrl+C 로 종료)", settings.bot_url)

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        connected = False
        while True:
            try:
                async with session.get(f"{settings.bot_url}/worker/next") as resp:
                    if resp.status == 204:
                        if not connected:
                            log.info("봇과 연결됨. 작업을 기다리는 중...")
                            connected = True
                        backoff = 5
                        continue
                    if resp.status in (401, 403, 404):
                        log.error("봇이 연결을 거부했습니다 (%s). Render 와 PC 의 WORKER_TOKEN 이 같은지, "
                                  "봇이 최신 버전으로 배포됐는지 확인하세요. 60초 후 다시 시도합니다.", resp.status)
                        connected = False
                        await asyncio.sleep(60)
                        continue
                    if resp.status != 200:
                        raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status)
                    job = await resp.json()
                connected = True
                result = await process(job, client)
                async with session.post(f"{settings.bot_url}/worker/result", json=result) as r:
                    if r.status != 200:
                        log.warning("결과 전달 실패 (%s)", r.status)
                backoff = 5
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if connected:
                    log.warning("봇과 연결이 끊겼습니다: %s", exc)
                connected = False
                log.info("%d초 후 다시 연결합니다. (봇이 재배포 중이거나 잠들어 있을 수 있음)", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
    await client.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("PC 수집기를 종료합니다.")


if __name__ == "__main__":
    main()
