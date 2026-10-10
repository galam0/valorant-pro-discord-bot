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
            timeout=aiohttp.ClientTimeout(total=15),
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


async def _download(url: str, max_bytes: int = MAX_BYTES) -> tuple[str, bytes | None]:
    """('ok', 바이트) / ('missing', None: 404 등 영구 실패) / ('retry', None: 일시 오류)"""
    try:
        session = await _get_session()
        async with session.get(url) as resp:
            if resp.status == 200:
                # StreamReader.read(n) 은 지금 버퍼에 있는 만큼만 돌려줘서 이미지가 잘릴 수 있다 → 끝까지 이어 받는다
                raw = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    raw += chunk
                    if len(raw) > max_bytes:
                        log.warning("이미지가 너무 커서 건너뜀 (%dMB 초과): %s", max_bytes // 1048576, url)
                        return "missing", None
                return "ok", bytes(raw)
            if resp.status in (404, 410):
                return "missing", None
            log.warning("이미지 응답 %s: %s", resp.status, url)
            return "retry", None
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("이미지 다운로드 실패: %s (%s: %s)", url, type(exc).__name__, exc)
        return "retry", None


async def fetch_image(url: str | None, max_bytes: int = MAX_BYTES) -> Image.Image | None:
    if not url or not url.startswith(("https://", "http://")):
        return None
    if url in _CACHE:
        _CACHE.move_to_end(url)
        return _CACHE[url]

    async with _SEM:
        state, raw = await _download(url, max_bytes)
        if state == "retry":  # 일시 오류는 한 번 더 시도
            await asyncio.sleep(0.5)
            state, raw = await _download(url, max_bytes)

    if state == "retry":
        return None  # 캐시하지 않음 → 다음 요청 때 다시 시도
    img = await asyncio.to_thread(_decode, raw) if raw is not None else None
    if raw is not None and img is None:
        log.warning("이미지를 읽지 못했습니다 (깨진 파일?): %s", url)
        return None  # 이것도 캐시하지 않음 (한 번 실패했다고 영원히 빈 칸이 되지 않게)

    _CACHE[url] = img  # 404 등 확실히 없는 이미지만 None으로 캐시
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return img


def _decode_big(raw: bytes, size: int) -> Image.Image | None:
    try:
        img = Image.open(BytesIO(raw))
        img.load()
        img = img.convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        return img
    except Exception:
        return None


_BIG_CACHE: "OrderedDict[str, Image.Image]" = OrderedDict()


async def fetch_big(url: str | None, size: int = 640) -> Image.Image | None:
    """퀴즈 그림처럼 크게 쓰는 이미지 (작은 캐시 40장). 실패하면 None."""
    if not url or not url.startswith("https://"):
        return None
    if url in _BIG_CACHE:
        _BIG_CACHE.move_to_end(url)
        return _BIG_CACHE[url]
    async with _SEM:
        state, raw = await _download(url)
        if state == "retry":
            await asyncio.sleep(0.5)
            state, raw = await _download(url)
    if raw is None:
        return None
    img = await asyncio.to_thread(_decode_big, raw, size)
    if img is not None:
        _BIG_CACHE[url] = img
        if len(_BIG_CACHE) > 40:
            _BIG_CACHE.popitem(last=False)
    return img


async def fetch_many(urls: dict[str, str | None], max_bytes: int = MAX_BYTES) -> dict[str, Image.Image | None]:
    keys = list(urls)
    t0 = time.perf_counter()
    cached = sum(1 for k in keys if urls[k] in _CACHE)
    results = await asyncio.gather(*(fetch_image(urls[k], max_bytes) for k in keys))
    log.info("[성능] 이미지 %d장 (캐시 %d) %dms", len([k for k in keys if urls[k]]), cached, (time.perf_counter() - t0) * 1000)
    return dict(zip(keys, results))
