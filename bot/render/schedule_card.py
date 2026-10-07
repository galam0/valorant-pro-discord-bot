"""경기 일정 이미지 카드 — 'NEXT MATCHES' 포스터 스타일 (검은 배경 + 금색 장식, 큰 팀 태그·로고·VS).

특정 대회의 공식 로고/상표는 쓰지 않는다. 분위기만 비슷한 자체 디자인.
"""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import LIVE, MUTED, RED, TEXT, fit_text, font, paste_logo, pill, text_w, to_png

W = 1080
PAD = 60
BG0 = (13, 13, 15)
GOLD_LIGHT = (240, 214, 150)
GOLD = (201, 163, 84)
GOLD_DARK = (150, 112, 45)
WIN = (61, 220, 151)

TOP_H = 650           # 제목·날짜 영역
BLOCK_H = 270         # 경기 하나
FOOTER_H = 90
MAX_LOGO = 150


def _background(w: int, h: int) -> Image.Image:
    """어두운 바탕 + 은은한 사선 빛줄기."""
    img = Image.new("RGB", (w, h), BG0).convert("RGBA")
    over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    step = 520
    for i, x0 in enumerate(range(-h, w, step)):
        alpha = 4 + (i % 3) * 3
        d.polygon([(x0, 0), (x0 + 90, 0), (x0 + 90 + h, h), (x0 + h, h)], fill=(255, 255, 255, alpha))
    return Image.alpha_composite(img, over).convert("RGB")


def _gradient_text(img: Image.Image, center: tuple[int, int], text: str, size: int, max_w: int,
                   colors: tuple[tuple[int, int, int], ...]) -> int:
    """세로 그라데이션 글자. 실제 쓴 글자 높이를 돌려준다."""
    f = font("heavy", size)
    d = ImageDraw.Draw(img)
    while size > 40 and text_w(d, text, f) > max_w:
        size -= 4
        f = font("heavy", size)
    bbox = d.textbbox((0, 0), text, font=f, anchor="lt")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    mask = Image.new("L", (tw + 8, th + 8), 0)
    ImageDraw.Draw(mask).text((4 - bbox[0], 4 - bbox[1]), text, font=f, fill=255, anchor="lt")
    grad = Image.new("RGB", mask.size)
    gd = ImageDraw.Draw(grad)
    n = len(colors) - 1
    for y in range(mask.height):
        t = y / max(mask.height - 1, 1) * n
        i = min(int(t), n - 1)
        f_ = t - i
        c = tuple(int(colors[i][k] + (colors[i + 1][k] - colors[i][k]) * f_) for k in range(3))
        gd.line([(0, y), (mask.width, y)], fill=c)
    img.paste(grad, (center[0] - mask.width // 2, center[1] - mask.height // 2), mask)
    return mask.height


def _ornament(d: ImageDraw.ImageDraw, y: int, half_gap: int) -> None:
    """가운데(날짜)를 비우고 양옆에 금색 장식선 + 모서리 꺾임."""
    cx = W // 2
    for sign in (-1, 1):
        x_in = cx + sign * half_gap
        x_out = cx + sign * (W // 2 - PAD)
        d.line([(x_in, y), (x_out, y)], fill=GOLD, width=3)
        d.line([(x_out, y), (x_out, y + 26)], fill=GOLD, width=3)           # 모서리 꺾임


def _divider(d: ImageDraw.ImageDraw, y: int) -> None:
    d.line([(PAD, y), (W - PAD, y)], fill=GOLD_DARK, width=2)
    for x in (PAD, W - PAD, W // 2):
        d.polygon([(x - 8, y), (x, y - 7), (x + 8, y), (x, y + 7)], fill=GOLD)


def render_schedule_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: {event, title_sub, date, rows:[{tag1, tag2, team1, team2, score1, score2, status, time, time_utc,
    stage, logo1, logo2}], more, footer, empty_message}"""
    logos = logos or {}
    rows: list[dict[str, Any]] = data["rows"]
    body = max(len(rows), 1) * BLOCK_H
    H = TOP_H + body + (50 if data.get("more") else 0) + FOOTER_H
    img = _background(W, H)
    d = ImageDraw.Draw(img)

    # --- 제목 영역 ---
    ev = data.get("event") or ""
    if ev:
        e, ef = fit_text(d, ev.upper(), "bold", 28, W - PAD * 2, 16)
        d.text((W // 2, 62), e, font=ef, fill=GOLD, anchor="mm")
        d.line([(W // 2 - 60, 94), (W // 2 + 60, 94)], fill=GOLD_DARK, width=2)
    gold_word, white_word = data.get("title_words", ("NEXT", "MATCHES"))
    _gradient_text(img, (W // 2, 205), gold_word, 210, 700, (GOLD_LIGHT, GOLD, GOLD_DARK))
    d = ImageDraw.Draw(img)
    big, bf = fit_text(d, white_word, "heavy", 190, W - PAD * 2, 90)
    d.text((W // 2, 385), big, font=bf, fill=TEXT, anchor="mm")
    d.text((W // 2, 505), data.get("title_sub", ""), font=font("bold", 26), fill=MUTED, anchor="mm")

    date_font = font("heavy", 50)
    date_w = text_w(d, data["date"], date_font)
    _ornament(d, 580, int(date_w / 2) + 40)
    d.text((W // 2, 580), data["date"], font=date_font, fill=TEXT, anchor="mm")

    # --- 경기 ---
    y0 = TOP_H
    if not rows:
        d.text((W // 2, y0 + 110), data.get("empty_message") or "예정된 경기가 없습니다.",
               font=font("bold", 30), fill=MUTED, anchor="mm")
    for i, r in enumerate(rows):
        top = y0 + i * BLOCK_H
        cy = top + 105
        # 태그 + 로고
        for side, tag_x, logo_x in ((1, 130, 335), (2, 950, 745)):
            tag, tf = fit_text(d, r[f"tag{side}"], "heavy", 74, 190, 32)
            d.text((tag_x, cy), tag, font=tf, fill=TEXT, anchor="mm")
            paste_logo(img, logos.get(r.get(f"logo{side}")), (logo_x, cy), MAX_LOGO, r[f"team{side}"])
        d = ImageDraw.Draw(img)
        # 가운데: VS / 스코어 / LIVE
        status = r["status"]
        if status in ("live", "completed") and r.get("score1") is not None:
            s1, s2 = r["score1"], r["score2"]
            win1 = status == "completed" and s1 > s2
            win2 = status == "completed" and s2 > s1
            d.text((W // 2 - 40, cy), str(s1), font=font("heavy", 70), fill=WIN if win1 else TEXT, anchor="mm")
            d.text((W // 2, cy - 4), ":", font=font("heavy", 54), fill=RED, anchor="mm")
            d.text((W // 2 + 40, cy), str(s2), font=font("heavy", 70), fill=WIN if win2 else TEXT, anchor="mm")
        else:
            d.text((W // 2, cy), "VS", font=font("heavy", 56), fill=RED, anchor="mm")
        if status == "live":
            pill(d, (W // 2 - 42, top + 14), "LIVE", LIVE, font("heavy", 20), h=34)
        # 시각 줄
        tline = f"{r['time']}   |   {r['time_utc']}"
        d.text((W // 2, top + 203), tline, font=font("bold", 26), fill=TEXT if status != "completed" else MUTED, anchor="mm")
        if r.get("stage"):
            st, sf = fit_text(d, r["stage"], "regular", 22, W - PAD * 2, 14)
            d.text((W // 2, top + 238), st, font=sf, fill=MUTED, anchor="mm")
        if i < len(rows) - 1:
            _divider(d, top + BLOCK_H - 8)

    yy = y0 + body
    if data.get("more"):
        d.text((W // 2, yy + 24), data["more"], font=font("bold", 24), fill=GOLD, anchor="mm")
    d.text((W // 2, H - FOOTER_H // 2), data.get("footer", ""), font=font("regular", 18), fill=MUTED, anchor="mm")
    return to_png(img)
