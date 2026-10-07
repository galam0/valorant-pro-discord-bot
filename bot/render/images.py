"""카드에 넣을 외부 이미지(팀 로고, 대회 로고, 선수 사진) 다운로드 + 메모리 캐시.

- 이미지는 디스크에 저장하지 않고 URL로 받아 메모리에만 보관한다 (최근 300개).
- 실패하면 None → 카드에서 이니셜 원으로 대체된다.
- 이미지 CDN(owcdn.net)은 HTML 페이지가 아니라서 스크래퍼용 2초 간격 제한을 적용하지 않고,
  대신 동시 다운로드 수를 제한한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from io import BytesIO

import aiohttp
from PIL import Image

from bot.scrapers.http import USER_AGENT

log = logging.getLogger("valobot.render.images")

_CACHE: OrderedDict[str, Image.Image | None] = OrderedDict()
_CACHE_MAX = 300
_SEM = asyncio.Semaphore(6)
_session: aiohttp.ClientSession | None = None
MAX_BYTES = 3 * 1024 * 1024


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8),
            headers={"User-Agent": USER_AGENT},
        )
    return _session


async def close() -> None:
    if _session is not None and not _session.closed:
        await _session.close()


def _decode(raw: bytes) -> Image.Image | None:
    try:
        img = Image.open(BytesIO(raw))
        img.load()
        img = img.convert("RGBA")
        img.thumbnail((256, 256), Image.LANCZOS)  # 카드에는 최대 150px로 들어가므로 미리 줄여 메모리 절약
        return img
    except Exception:
        return None


async def fetch_image(url: str | None) -> Image.Image | None:
    if not url or not url.startswith(("https://", "http://")):
        return None
    if url in _CACHE:
        _CACHE.move_to_end(url)
        return _CACHE[url]

    img: Image.Image | None = None
    async with _SEM:
        try:
            session = await _get_session()
            async with session.get(url) as resp:
                if resp.status == 200:
                    raw = await resp.content.read(MAX_BYTES + 1)
                    if len(raw) <= MAX_BYTES:
                        img = await asyncio.to_thread(_decode, raw)
                elif resp.status != 404:
                    log.debug("이미지 응답 %s: %s", resp.status, url)
                    return None  # 일시 오류는 캐시하지 않음
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.debug("이미지 다운로드 실패: %s (%s)", url, exc)
            return None

    _CACHE[url] = img  # 404·깨진 이미지는 None으로 캐시해서 반복 요청 방지
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return img


async def fetch_many(urls: dict[str, str | None]) -> dict[str, Image.Image | None]:
    keys = list(urls)
    t0 = time.perf_counter()
    cached = sum(1 for k in keys if urls[k] in _CACHE)
    results = await asyncio.gather(*(fetch_image(urls[k]) for k in keys))
    log.info("[성능] 이미지 %d장 (캐시 %d) %dms", len([k for k in keys if urls[k]]), cached, (time.perf_counter() - t0) * 1000)
    return dict(zip(keys, results))
