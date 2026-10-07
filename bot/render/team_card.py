"""팀 정보 이미지 카드: 로고, 로스터, 스태프, 최근 전적."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GOLD, GREEN, LINE, LIVE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, pill, text_w, to_png,
)

W = 1100
PAD = 30
HEADER_H = 230
BANNER_H = 70
CARD_COLS = 3
CARD_H = 100
CARD_GAP = 14
ROW_H = 58
FOOTER_H = 56


def _section_title(d: ImageDraw.ImageDraw, y: int, title: str, right: str = "") -> int:
    d.text((PAD, y), title, font=font("heavy", 24), fill=TEXT)
    if right:
        d.text((W - PAD, y + 4), right, font=font("bold", 19), fill=MUTED, anchor="ra")
    return y + 44


def render_team_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: build_team_card_data()가 만든 dict. logos: {'team': PIL.Image|None}"""
    logos = logos or {}
    players: list[dict[str, Any]] = data.get("players") or []
    staff: list[dict[str, Any]] = data.get("staff") or []
    recent: list[dict[str, Any]] = data.get("recent") or []
    banner = data.get("banner")

    player_rows = max(1, -(-len(players) // CARD_COLS))
    staff_h = 44 + 50 if staff else 0
    recent_h = 44 + max(1, len(recent)) * ROW_H + 24
    H = (HEADER_H + (BANNER_H + 16 if banner else 16) + 44 + player_rows * (CARD_H + CARD_GAP)
         + 10 + staff_h + 20 + recent_h + FOOTER_H)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # --- 머리: 로고, 팀명, 국가, 대회, 최근 기록 ---
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    paste_logo(img, logos.get("team"), (PAD + 85, HEADER_H // 2), 150, data["name"])

    x = PAD + 200
    name, nf = fit_text(d, data["name"], "heavy", 58, 520, 30)
    d.text((x, 44), name, font=nf, fill=TEXT)
    y = 124
    tf = font("bold", 19)
    if data.get("tag") and data["tag"] != data["name"]:
        x = pill(d, (x, y), data["tag"], PANEL_2, tf, h=34) + 10
    d.text((x, y + 17), data.get("country") or "", font=font("bold", 21), fill=TEXT, anchor="lm")
    if data.get("event"):
        ev, ef = fit_text(d, data["event"], "regular", 19, 480)
        d.text((PAD + 200, 172), ev, font=ef, fill=MUTED)

    # 최근 기록 요약 (오른쪽)
    if recent:
        wins = sum(1 for r in recent if r["result"] == "W")
        losses = sum(1 for r in recent if r["result"] == "L")
        bx1, bx0 = W - PAD, W - PAD - 250
        d.rounded_rectangle([bx0, 50, bx1, 180], radius=14, fill=PANEL_2)
        d.text(((bx0 + bx1) / 2, 76), f"최근 {len(recent)}경기", font=font("bold", 18), fill=MUTED, anchor="mm")
        d.text(((bx0 + bx1) / 2, 116), f"{wins}승 {losses}패", font=font("heavy", 34), fill=TEXT, anchor="mm")
        n = len(recent)
        dot, gap = 18, 8
        sx = (bx0 + bx1) / 2 - (n * dot + (n - 1) * gap) / 2
        for i, r in enumerate(reversed(recent)):  # 왼쪽이 오래된 경기
            color = GREEN if r["result"] == "W" else RED if r["result"] == "L" else MUTED
            cx = sx + i * (dot + gap)
            d.rounded_rectangle([cx, 148, cx + dot, 148 + dot], radius=5, fill=color)

    y = HEADER_H + 16

    # --- LIVE / 다음 경기 배너 ---
    if banner:
        live = banner["kind"] == "live"
        d.rounded_rectangle([PAD, y, W - PAD, y + BANNER_H], radius=14,
                            fill=(70, 24, 30) if live else PANEL, outline=LIVE if live else LINE, width=2)
        cy = y + BANNER_H / 2
        if live:
            pill(d, (PAD + 18, cy - 17), "● LIVE", LIVE, font("bold", 19))
            lx = PAD + 140
        else:
            d.text((PAD + 22, cy), "다음 경기", font=font("bold", 20), fill=MUTED, anchor="lm")
            lx = PAD + 140
        d.text((lx, cy), f"vs {banner['opponent']}", font=font("heavy", 26), fill=TEXT, anchor="lm")
        d.text((W - PAD - 22, cy), banner["right"], font=font("heavy" if live else "bold", 26 if live else 21),
               fill=TEXT, anchor="rm")
        y += BANNER_H + 16

    # --- 선수 카드 ---
    y = _section_title(d, y, "선수", f"{len(players)}명")
    cw = (W - PAD * 2 - CARD_GAP * (CARD_COLS - 1)) / CARD_COLS
    for i, p in enumerate(players):
        col, row = i % CARD_COLS, i // CARD_COLS
        x0 = PAD + col * (cw + CARD_GAP)
        y0 = y + row * (CARD_H + CARD_GAP)
        d.rounded_rectangle([x0, y0, x0 + cw, y0 + CARD_H], radius=14, fill=PANEL)
        # 아바타 (사진이 없으면 이니셜)
        av = p.get("photo")
        paste_logo(img, av, (int(x0 + 52), int(y0 + CARD_H / 2)), 68, p["name"])
        tx = x0 + 100
        nm, nmf = fit_text(d, p["name"], "heavy", 26, cw - 120 - (30 if p.get("captain") else 0), 16)
        d.text((tx, y0 + 26), nm, font=nmf, fill=TEXT)
        if p.get("captain"):
            d.text((tx + text_w(d, nm, nmf) + 10, y0 + 30), "★", font=font("heavy", 22), fill=GOLD)
        sub = p.get("real_name") or ""
        if p.get("role"):
            rx = pill(d, (tx, y0 + 62), p["role"], (58, 74, 90), font("bold", 15), h=26, pad_x=10)
            if sub:
                s, sf = fit_text(d, sub, "regular", 16, x0 + cw - rx - 18)
                d.text((rx + 8, y0 + 75), s, font=sf, fill=MUTED, anchor="lm")
        elif sub:
            s, sf = fit_text(d, sub, "regular", 17, cw - 120)
            d.text((tx, y0 + 64), s, font=sf, fill=MUTED)
    y += player_rows * (CARD_H + CARD_GAP) + 10

    # --- 스태프 ---
    if staff:
        y = _section_title(d, y, "코칭 스태프")
        x = PAD
        for s in staff:
            label = f"{s['name']}  ·  {s['role']}"
            f = font("bold", 19)
            w = text_w(d, label, f) + 32
            if x + w > W - PAD:
                break
            d.rounded_rectangle([x, y, x + w, y + 40], radius=20, fill=PANEL)
            d.text((x + w / 2, y + 20), label, font=f, fill=TEXT, anchor="mm")
            x += w + 10
        y += 50
    y += 20

    # --- 최근 전적 ---
    y = _section_title(d, y, "최근 전적")
    if not recent:
        d.text((PAD, y + 10), "기록 없음", font=font("regular", 20), fill=MUTED)
    for i, r in enumerate(recent):
        y0 = y + i * ROW_H
        if i % 2 == 0:
            d.rounded_rectangle([PAD, y0, W - PAD, y0 + ROW_H - 4], radius=10, fill=PANEL)
        cy = y0 + (ROW_H - 4) / 2
        color = GREEN if r["result"] == "W" else RED if r["result"] == "L" else MUTED
        label = {"W": "승", "L": "패"}.get(r["result"], "-")
        d.rounded_rectangle([PAD + 14, cy - 17, PAD + 54, cy + 17], radius=8, fill=color)
        d.text((PAD + 34, cy), label, font=font("heavy", 20), fill=BG, anchor="mm")
        d.text((PAD + 74, cy), r["score"], font=font("heavy", 24), fill=TEXT, anchor="lm")
        opp, of = fit_text(d, r["opponent"], "bold", 23, 330)
        d.text((PAD + 160, cy), opp, font=of, fill=TEXT, anchor="lm")
        right = r.get("date") or ""
        d.text((W - PAD - 18, cy), right, font=font("regular", 18), fill=MUTED, anchor="rm")
        if r.get("event"):
            ev, ef = fit_text(d, r["event"], "regular", 18, 300)
            d.text((W - PAD - 18 - text_w(d, right, font("regular", 18)) - 24, cy), ev,
                   font=ef, fill=MUTED, anchor="rm")

    # --- 바닥글 ---
    fy = H - FOOTER_H
    d.line([PAD, fy, W - PAD, fy], fill=LINE, width=1)
    d.text((PAD, fy + FOOTER_H / 2), "출처: VLR.gg", font=font("regular", 16), fill=MUTED, anchor="lm")
    if data.get("updated"):
        d.text((W - PAD, fy + FOOTER_H / 2), f"{data['updated']} 기준", font=font("regular", 16), fill=MUTED, anchor="rm")
    return to_png(img)
