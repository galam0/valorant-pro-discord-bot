"""/프로필 카드 (VP 상점에서 산 꾸미기 적용). 지금은 시안 단계."""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from bot.render.base import GOLD, GREEN, MUTED, RED, TEXT, fit_text, font

W, H = 800, 420

THEMES = {   # 배경 (위, 아래, 포인트)
    "default": ((24, 36, 50), (12, 18, 27), (255, 70, 85)),
    "sunset": ((90, 36, 70), (30, 14, 40), (255, 140, 90)),
    "ocean": ((14, 70, 100), (6, 22, 44), (90, 220, 255)),
    "gold": ((70, 52, 14), (22, 16, 6), (255, 210, 70)),
    "forest": ((16, 70, 52), (6, 26, 22), (110, 230, 160)),
}
FRAMES = {"none": None, "silver": (200, 205, 215), "gold": (255, 205, 60), "rainbow": "rainbow", "neon": (90, 255, 240)}


def _gradient(top, bottom) -> Image.Image:
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def _avatar(size: int, avatar: Image.Image | None, name: str, accent) -> Image.Image:
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    if avatar is not None:
        a = avatar.convert("RGBA").resize((size, size), Image.LANCZOS)
        base.paste(a, (0, 0), mask)
    else:
        d = ImageDraw.Draw(base)
        d.ellipse([0, 0, size - 1, size - 1], fill=tuple(int(c * 0.55) for c in accent))
        d.text((size / 2, size / 2), name[:1].upper(), font=font("heavy", int(size * 0.5)), fill=TEXT, anchor="mm")
    return base


def _ring(img: Image.Image, cx: int, cy: int, r: int, frame: str) -> None:
    color = FRAMES.get(frame)
    if color is None:
        return
    d = ImageDraw.Draw(img)
    if color == "rainbow":
        for deg in range(0, 360, 2):
            h = deg / 360
            c = tuple(int(255 * v) for v in _hsv(h))
            a0 = deg - 2
            d.arc([cx - r, cy - r, cx + r, cy + r], a0, deg + 1, fill=c, width=9)
    else:
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([cx - r, cy - r, cx + r, cy + r], outline=color + (255,), width=12)
        glow = glow.filter(ImageFilter.GaussianBlur(6))
        img.paste(glow, (0, 0), glow)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=6)


def _hsv(h: float):
    i = int(h * 6)
    f = h * 6 - i
    q, t = 1 - f, f
    return [(1, t, 0), (q, 1, 0), (0, 1, t), (0, q, 1), (t, 0, 1), (1, 0, q)][i % 6]


def render_profile_card(data: dict[str, Any], avatar: Image.Image | None = None) -> bytes:
    """data: name, title, theme, frame, vp, rank, rank_total, pred_win, pred_total, quiz_week, fav_team, fav_agent, badges[]"""
    top, bottom, accent = THEMES.get(data.get("theme", "default"), THEMES["default"])
    img = _gradient(top, bottom)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([14, 14, W - 15, H - 15], radius=26, outline=accent + (140,), width=3)
    d.polygon([(W - 260, 0), (W, 0), (W, 160)], fill=accent + (38,))

    cx, cy, r = 130, 150, 78
    av = _avatar(r * 2, avatar, data["name"], accent)
    img.paste(av, (cx - r, cy - r), av)
    _ring(img, cx, cy, r + 8, data.get("frame", "none"))
    d = ImageDraw.Draw(img, "RGBA")

    x = 245
    name, nf = fit_text(d, data["name"], "heavy", 44, W - x - 40, 26)
    d.text((x, 92), name, font=nf, fill=TEXT, anchor="lm")
    if data.get("title"):
        tw = d.textlength(data["title"], font=font("bold", 20))
        d.rounded_rectangle([x, 128, x + tw + 28, 160], radius=16, fill=accent + (70,), outline=accent, width=2)
        d.text((x + 14, 144), data["title"], font=font("bold", 20), fill=TEXT, anchor="lm")
    badges = data.get("badges", [])
    for i, b in enumerate(badges[:5]):
        bx = x + i * 44
        d.ellipse([bx, 178, bx + 36, 214], fill=(255, 255, 255, 28), outline=accent + (200,), width=2)
        d.text((bx + 18, 196), b, font=font("heavy", 18), fill=accent, anchor="mm")

    # 통계 칸
    cells = [("VP", f"{data['vp']:,}", GOLD), ("서버 순위", f"{data['rank']}위", TEXT),
             ("예측 적중", f"{data['pred_win']}/{data['pred_total']}", GREEN), ("이번 주 퀴즈", f"{data['quiz_week']}/5", TEXT)]
    cw = (W - 80) / 4
    for i, (label, val, col) in enumerate(cells):
        x0 = 40 + cw * i
        d.rounded_rectangle([x0 + 4, 250, x0 + cw - 4, 340], radius=16, fill=(0, 0, 0, 90))
        v, vf = fit_text(d, val, "heavy", 30, cw - 30, 18)
        d.text((x0 + cw / 2, 285), v, font=vf, fill=col, anchor="mm")
        d.text((x0 + cw / 2, 322), label, font=font("regular", 15), fill=MUTED, anchor="mm")
    d.text((40, 372), f"응원 팀  {data.get('fav_team', '-')}", font=font("bold", 20), fill=TEXT, anchor="lm")
    d.text((W - 40, 372), f"최애 요원  {data.get('fav_agent', '-')}", font=font("bold", 20), fill=TEXT, anchor="rm")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
