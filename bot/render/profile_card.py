"""/프로필 카드 (가로 배너형: 팔각형 아바타 + 사선 포인트). 꾸미기 아이템(배경·테두리·칭호)이 반영된다."""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import fit_text, font

W, H = 800, 300
NAVY = (27, 36, 51)
WHITE = (250, 247, 240)
DIM = (150, 162, 182)

# 배경 테마: (바탕, 줄무늬, 포인트)
THEMES = {
    "theme_default": ((30, 42, 58), (36, 50, 69), (255, 70, 85)),
    "theme_sunset": ((92, 48, 96), (104, 56, 108), (255, 150, 100)),
    "theme_ocean": ((22, 84, 120), (28, 96, 134), (110, 225, 255)),
    "theme_forest": ((28, 84, 62), (34, 96, 72), (150, 235, 150)),
    "theme_gold": ((58, 46, 20), (70, 56, 26), (255, 205, 70)),
}
RAINBOW = [(232, 67, 79), (255, 150, 60), (255, 214, 70), (80, 200, 120), (80, 170, 240), (150, 100, 230)]
FRAME_COLORS = {"frame_silver": ((200, 206, 216), (140, 148, 162)), "frame_gold": ((255, 205, 60), (214, 150, 20)),
                "frame_neon": ((90, 245, 235), (30, 150, 160))}



def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _ink(accent) -> tuple[int, int, int]:
    """포인트 색 위에 올릴 글자색 (밝은 포인트면 어두운 글자)."""
    return NAVY if _lum(accent) > 150 else (255, 255, 255)


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _octagon(x0: float, y0: float, s: float, cut: float = 0.2) -> list[tuple[float, float]]:
    c = s * cut
    return [(x0 + c, y0), (x0 + s - c, y0), (x0 + s, y0 + c), (x0 + s, y0 + s - c),
            (x0 + s - c, y0 + s), (x0 + c, y0 + s), (x0, y0 + s - c), (x0, y0 + c)]


def _octagon_mask(size: int) -> Image.Image:
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).polygon(_octagon(0, 0, size * 4 - 1), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def _background(theme: str) -> Image.Image:
    base, stripe, _ = THEMES.get(theme, THEMES["theme_default"])
    img = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(img)
    dark = _mix(base, (8, 10, 18), 0.7)
    for x in range(W):                      # 왼쪽 → 오른쪽으로 어두워지는 바탕
        d.line([(x, 0), (x, H)], fill=_mix(base, dark, x / W))
    for i in range(-H, W, 56):              # 테마색 사선 줄무늬
        d.line([(i, H), (i + H, 0)], fill=_mix(stripe, dark, 0.35), width=10)
    return img


def _avatar(size: int, avatar: Image.Image | None, name: str, accent) -> Image.Image:
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if avatar is not None:
        base.paste(avatar.convert("RGBA").resize((size, size), Image.LANCZOS), (0, 0))
    else:
        d = ImageDraw.Draw(base)
        d.rectangle([0, 0, size, size], fill=accent)
        d.text((size / 2, size / 2), (name[:1] or "?").upper(), font=font("heavy", int(size * 0.5)), fill=_ink(accent), anchor="mm")
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), _octagon_mask(size))
    return out


def _hue_color(t: float) -> tuple[int, int, int]:
    """t(0~1) → 무지개 색 (RAINBOW 색들 사이를 부드럽게 이어서 한 바퀴)."""
    n = len(RAINBOW)
    pos = (t % 1.0) * n
    i, f = int(pos), pos - int(pos)
    a, b = RAINBOW[i % n], RAINBOW[(i + 1) % n]
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))


def _rainbow_fill(img: Image.Image, poly: list[tuple[float, float]]) -> None:
    """다각형 안을 중심 기준 각도에 따라 색이 이어지는 무지개 그라데이션으로 채운다 (끊김 없는 링)."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, y0, x1, y1 = int(min(xs)) - 1, int(min(ys)) - 1, int(max(xs)) + 2, int(max(ys)) + 2
    w, h = x1 - x0, y1 - y0
    cx, cy = w / 2, h / 2
    grad = Image.new("RGB", (w, h))
    px = grad.load()
    for y in range(h):
        for x in range(w):
            ang = (math.atan2(y - cy, x - cx) / (2 * math.pi) + 0.25) % 1.0
            px[x, y] = _hue_color(ang)
    mask = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(mask).polygon([((px_ - x0) * 3, (py_ - y0) * 3) for px_, py_ in poly], fill=255)
    img.paste(grad, (x0, y0), mask.resize((w, h), Image.LANCZOS))


def _draw_frame(img: Image.Image, x0: int, y0: int, s: int, frame: str) -> None:
    """팔각형 아바타(x0, y0, 한 변 s) 바깥에 테두리를 그린다 (두께 16)."""
    d = ImageDraw.Draw(img)
    t = 16
    if frame == "frame_none":
        d.polygon(_octagon(x0 - 5, y0 - 5, s + 10), outline=WHITE, width=5)
        return
    outer = _octagon(x0 - t, y0 - t, s + 2 * t)
    d.polygon(_octagon(x0 - t - 4, y0 - t - 4, s + 2 * t + 8), fill=NAVY)
    if frame == "frame_rainbow":
        _rainbow_fill(img, outer)
    else:
        main, dark = FRAME_COLORS[frame]
        d.polygon(outer, fill=main)
        d.line(outer[:3], fill=dark, width=4)
        if frame == "frame_gold":      # 모서리 보석
            for gx, gy in outer[1::2]:
                d.polygon([(gx, gy - 8), (gx + 7, gy), (gx, gy + 8), (gx - 7, gy)], fill=(232, 67, 79), outline=NAVY)
    d.polygon(_octagon(x0 - 4, y0 - 4, s + 8), fill=NAVY)


def render_profile_card(data: dict[str, Any], avatar: Image.Image | None = None) -> bytes:
    """data: name, title(표시용 글자 또는 ''), theme, frame, vp, rank, pred_win, pred_total,
    fav_team, fav_agent"""
    theme = data.get("theme", "theme_default")
    base, _, accent = THEMES.get(theme, THEMES["theme_default"])
    ink = _ink(accent)
    img = _background(theme)
    d = ImageDraw.Draw(img)
    panel = _mix(base, (8, 10, 18), 0.78)
    d.polygon([(690, 0), (W, 0), (W, H), (600, H)], fill=accent)                 # 오른쪽 사선 포인트 면
    d.polygon([(712, 0), (W, 0), (W, H), (622, H)], fill=panel)

    s, ax, ay = 204, 44, 48
    _draw_frame(img, ax, ay, s, data.get("frame", "frame_none"))
    av = _avatar(s, avatar, data["name"], accent)
    img.paste(av, (ax, ay), av)
    d = ImageDraw.Draw(img)

    x = 290
    name, nf = fit_text(d, data["name"], "heavy", 50, 390, 28)
    d.text((x, 78), name, font=nf, fill=WHITE, anchor="lm")
    tx = x
    if data.get("title"):
        f = font("bold", 18)
        tw = d.textlength(data["title"], font=f)
        d.rounded_rectangle([x, 118, x + tw + 28, 150], radius=5, fill=accent)
        d.text((x + 14 + tw / 2, 134), data["title"], font=f, fill=ink, anchor="mm")
        tx = x + tw + 28 + 14
    agent = data.get("fav_agent") or "-"
    d.text((tx, 134), f"최애 요원 · {agent}", font=font("regular", 17), fill=(170, 182, 200), anchor="lm")

    pw = data["pred_total"]
    rate = f"{round(100 * data['pred_win'] / pw)}%" if pw else "-"
    stats = [(f"{data['vp']:,}", "VP", WHITE), (rate, "예측 적중률", WHITE), (data.get("fav_team") or "-", "응원 팀", WHITE)]
    for i, (val, label, col) in enumerate(stats):
        sx = x + i * 110
        v, vf = fit_text(d, val, "heavy", 32, 98, 16)
        d.text((sx, 206), v, font=vf, fill=col, anchor="lm")
        d.line([(sx, 232), (sx + 82, 232)], fill=accent, width=3)
        d.text((sx, 254), label, font=font("regular", 15), fill=DIM, anchor="lm")

    d.text((W - 38, 96), "RANK", font=font("bold", 16), fill=_mix(accent, WHITE, 0.4), anchor="rm")
    d.text((W - 38, 176), f"#{data['rank']}", font=font("heavy", 84), fill=WHITE, anchor="rm")
    d.text((W - 38, 240), "서버 순위", font=font("regular", 16), fill=(170, 182, 200), anchor="rm")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
