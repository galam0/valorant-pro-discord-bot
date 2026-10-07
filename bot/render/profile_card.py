"""/프로필 카드 (플랫 스타일: 단색 면 + 굵은 외곽선). 꾸미기 아이템(배경·테두리·칭호)이 반영된다."""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import fit_text, font

W, H = 800, 420
NAVY = (27, 36, 51)
WHITE = (250, 247, 240)

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


def _background(theme: str) -> Image.Image:
    base, stripe, _ = THEMES.get(theme, THEMES["theme_default"])
    img = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(img)
    for i in range(-H, W, 56):
        d.line([(i, H), (i + H, 0)], fill=stripe, width=18)
    return img


def _avatar(size: int, avatar: Image.Image | None, name: str, accent) -> Image.Image:
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    if avatar is not None:
        base.paste(avatar.convert("RGBA").resize((size, size), Image.LANCZOS), (0, 0), mask)
    else:
        d = ImageDraw.Draw(base)
        d.ellipse([0, 0, size - 1, size - 1], fill=accent)
        d.text((size / 2, size / 2), (name[:1] or "?").upper(), font=font("heavy", int(size * 0.5)), fill=WHITE, anchor="mm")
    return base


def _draw_frame(img: Image.Image, cx: int, cy: int, r: int, frame: str) -> None:
    """r: 아바타 반지름. 링은 그 바깥에 그린다 (두께 12)."""
    if frame == "frame_none":
        d = ImageDraw.Draw(img)
        d.ellipse([cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5], outline=NAVY, width=6)
        return
    d = ImageDraw.Draw(img)
    out, inn = r + 18, r
    d.ellipse([cx - out - 4, cy - out - 4, cx + out + 4, cy + out + 4], fill=NAVY)
    if frame == "frame_rainbow":
        n = len(RAINBOW)
        for i, col in enumerate(RAINBOW):
            d.pieslice([cx - out, cy - out, cx + out, cy + out], i * 360 / n, (i + 1) * 360 / n, fill=col)
    else:
        main, dark = FRAME_COLORS[frame]
        d.ellipse([cx - out, cy - out, cx + out, cy + out], fill=main)
        d.arc([cx - out + 5, cy - out + 5, cx + out - 5, cy + out - 5], 20, 110, fill=dark, width=5)
        if frame == "frame_gold":      # 보석 4개
            for k in range(4):
                a = math.radians(45 + 90 * k)
                gx, gy = cx + (r + 9) * math.cos(a), cy + (r + 9) * math.sin(a)
                d.polygon([(gx, gy - 8), (gx + 7, gy), (gx, gy + 8), (gx - 7, gy)], fill=(232, 67, 79), outline=NAVY)
    d.ellipse([cx - inn - 4, cy - inn - 4, cx + inn + 4, cy + inn + 4], fill=NAVY)


def render_profile_card(data: dict[str, Any], avatar: Image.Image | None = None) -> bytes:
    """data: name, title(표시용 글자 또는 ''), theme, frame, vp, rank, pred_win, pred_total, quiz_week, quiz_limit,
    fav_team, fav_agent"""
    theme = data.get("theme", "theme_default")
    accent = THEMES.get(theme, THEMES["theme_default"])[2]
    img = _background(theme)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([14, 14, W - 15, H - 15], radius=28, outline=NAVY, width=6)

    cx, cy, r = 128, 128, 64
    _draw_frame(img, cx, cy, r, data.get("frame", "frame_none"))
    av = _avatar(r * 2, avatar, data["name"], accent)
    img.paste(av, (cx - r, cy - r), av)
    d = ImageDraw.Draw(img)

    x = 250
    name, nf = fit_text(d, data["name"], "heavy", 46, W - x - 40, 26)
    d.text((x, 88), name, font=nf, fill=WHITE, anchor="lm")
    if data.get("title"):
        f = font("bold", 20)
        tw = d.textlength(data["title"], font=f)
        d.rounded_rectangle([x, 124, x + tw + 30, 158], radius=17, fill=accent, outline=NAVY, width=3)
        d.text((x + 15, 141), data["title"], font=f, fill=NAVY, anchor="lm")
    pw = data["pred_total"]
    rate = f"{round(100 * data['pred_win'] / pw)}%" if pw else "-"
    d.text((x, 190), f"예측 적중률  {rate}", font=font("bold", 18), fill=(200, 208, 218), anchor="lm")

    cells = [("VP", f"{data['vp']:,}", (255, 214, 95)), ("서버 순위", f"{data['rank']}위", WHITE),
             ("예측 적중", f"{data['pred_win']}/{data['pred_total']}", (120, 230, 160)),
             ("이번 주 퀴즈", f"{data['quiz_week']}/{data.get('quiz_limit', 5)}", WHITE)]
    cw = (W - 80) / 4
    for i, (label, val, col) in enumerate(cells):
        x0 = 40 + cw * i
        d.rounded_rectangle([x0 + 5, 236, x0 + cw - 5, 330], radius=18, fill=NAVY)
        v, vf = fit_text(d, val, "heavy", 32, cw - 34, 18)
        d.text((x0 + cw / 2, 273), v, font=vf, fill=col, anchor="mm")
        d.text((x0 + cw / 2, 311), label, font=font("regular", 15), fill=(150, 162, 178), anchor="mm")
    d.rounded_rectangle([40, 346, W - 40, 390], radius=14, fill=NAVY)
    d.text((58, 368), f"응원 팀  {data.get('fav_team') or '-'}", font=font("bold", 19), fill=WHITE, anchor="lm")
    d.text((W - 58, 368), f"최애 요원  {data.get('fav_agent') or '-'}", font=font("bold", 19), fill=WHITE, anchor="rm")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
