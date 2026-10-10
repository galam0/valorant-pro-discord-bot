"""사목 판 그림: 나무 판 + 흑돌·백돌 (+ 원하면 팀 로고를 판에 새김).

느린 서버에서도 한 수에 수십 ms 안에 그리도록, 나무 무늬·돌 그림은 한 번 만들어 재사용한다.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from bot.render.base import BG, TEXT, font

CELL = 76          # 한 칸 크기
PAD = 22           # 판 바깥 여백
TOP = 54           # 번호 줄 높이
STONE = CELL - 16  # 돌 지름
WIN_RING = (255, 196, 64)
LAST_DOT = (230, 60, 60)


@lru_cache(maxsize=4)
def _wood(w: int, h: int) -> Image.Image:
    """나무 결 무늬 (가로 결, 따뜻한 갈색)."""
    rng = random.Random(7)
    img = Image.new("RGB", (w, h), (176, 120, 70))
    d = ImageDraw.Draw(img)
    y = 0.0
    while y < h:
        shade = rng.uniform(-28, 22)
        base = (176 + shade, 120 + shade * 0.8, 70 + shade * 0.5)
        thick = rng.uniform(1.5, 5.5)
        amp, freq, phase = rng.uniform(1, 6), rng.uniform(0.004, 0.012), rng.uniform(0, 6.3)
        pts = [(x, y + amp * math.sin(x * freq + phase)) for x in range(0, w + 8, 8)]
        d.line(pts, fill=tuple(int(max(0, min(255, c))) for c in base), width=max(1, int(thick)))
        y += thick * rng.uniform(0.6, 1.1)
    for _ in range(3):   # 옹이
        cx, cy, r = rng.randrange(w), rng.randrange(h), rng.randrange(10, 22)
        for k in range(r, 0, -3):
            d.ellipse([cx - k * 1.8, cy - k, cx + k * 1.8, cy + k], outline=(120, 76, 40), width=1)
    return img.filter(ImageFilter.GaussianBlur(0.8))


@lru_cache(maxsize=2)
def _stone(color: int) -> Image.Image:
    """흑돌(1)·백돌(2). 바둑돌처럼 가운데가 밝고 가장자리가 어두운 공 모양."""
    s = STONE * 2          # 크게 그려서 줄이면 테두리가 매끈하다
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    dark, light = ((20, 20, 24), (95, 95, 105)) if color == 1 else ((178, 176, 168), (252, 252, 248))
    steps = 40
    for i in range(steps):
        t = i / (steps - 1)
        r = s / 2 * (1 - t * 0.9)
        off = s * 0.12 * t                       # 빛이 왼쪽 위에서 온다
        c = tuple(int(dark[k] + (light[k] - dark[k]) * t ** 1.6) for k in range(3))
        d.ellipse([s / 2 - r - off, s / 2 - r - off, s / 2 + r - off, s / 2 + r - off], fill=c + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, s - 1, s - 1], fill=255)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img.resize((STONE, STONE), Image.LANCZOS)


def _shadow(size: int) -> Image.Image:
    sh = Image.new("RGBA", (size + 16, size + 16), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([8, 10, size + 8, size + 10], fill=(0, 0, 0, 120))
    return sh.filter(ImageFilter.GaussianBlur(4))


def render_board(board, last: tuple[int, int] | None = None, logo: Image.Image | None = None) -> bytes:
    rows, cols = len(board.grid), len(board.grid[0])
    w = PAD * 2 + cols * CELL
    h = TOP + PAD + rows * CELL
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    # 위 번호 (버튼 번호와 같음). 꽉 찬 줄은 흐리게
    f = font("heavy", 26)
    for c in range(cols):
        x = PAD + c * CELL + CELL // 2
        d.text((x, TOP // 2 + 2), str(c + 1), font=f, fill=(90, 100, 112) if board.grid[0][c] else TEXT, anchor="mm")

    # 나무 판 (테두리는 조금 더 어둡게)
    bx0, by0, bx1, by1 = PAD - 8, TOP - 8, w - PAD + 8, h - PAD + 8
    wood = _wood(bx1 - bx0, by1 - by0)
    mask = Image.new("L", wood.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, wood.width - 1, wood.height - 1], radius=18, fill=255)
    frame = Image.eval(wood, lambda v: int(v * 0.72))
    img.paste(frame, (bx0, by0), mask)
    inner = Image.new("L", wood.size, 0)
    ImageDraw.Draw(inner).rounded_rectangle([5, 5, wood.width - 6, wood.height - 6], radius=14, fill=255)
    img.paste(wood, (bx0, by0), inner)

    # 구멍(살짝 파인 홈)
    d = ImageDraw.Draw(img)
    m = (CELL - STONE) // 2
    for r in range(rows):
        for c in range(cols):
            x0, y0 = PAD + c * CELL + m, TOP + r * CELL + m
            d.ellipse([x0 + 3, y0 + 3, x0 + STONE - 3, y0 + STONE - 3], fill=(92, 58, 30))
            d.ellipse([x0 + 3, y0 + 5, x0 + STONE - 3, y0 + STONE - 1], fill=(124, 82, 46))

    # 팀 로고: 판 가운데에 새긴 것처럼 옅게
    if logo is not None:
        lg = logo.convert("RGBA")
        side = int(min(cols * CELL, rows * CELL) * 0.78)
        lg.thumbnail((side, side), Image.LANCZOS)
        alpha = lg.getchannel("A").point(lambda a: int(a * 0.42))
        burnt = Image.new("RGBA", lg.size, (70, 38, 16, 255))     # 인두로 지진 듯한 갈색
        burnt.putalpha(alpha)
        img.paste(burnt, (PAD + (cols * CELL - lg.width) // 2, TOP + (rows * CELL - lg.height) // 2), burnt)

    # 돌
    d = ImageDraw.Draw(img)
    win = set(board.line)
    shadow = _shadow(STONE)
    for r in range(rows):
        for c in range(cols):
            x0, y0 = PAD + c * CELL + m, TOP + r * CELL + m
            x1, y1 = x0 + STONE, y0 + STONE
            v = board.grid[r][c]
            if not v:
                continue
            img.paste(shadow, (x0 - 8, y0 - 8), shadow)
            stone = _stone(v)
            img.paste(stone, (x0, y0), stone)
            if (r, c) in win:
                d.ellipse([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=WIN_RING, width=5)
            elif last == (r, c):
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=LAST_DOT)   # 방금 둔 돌
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
