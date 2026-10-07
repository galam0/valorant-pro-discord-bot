"""경기 일정 이미지 카드 (하루치 경기를 시간순으로)."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GREEN, LINE, LIVE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, pill, to_png,
)

W = 1000
PAD = 30
HEADER_H = 130
ROW_H = 86
FOOTER_H = 52


def render_schedule_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: {title, subtitle, rows: [{time, team1, team2, score1, score2, status, event, logo1, logo2}], more, footer, empty_message}"""
    logos = logos or {}
    rows: list[dict[str, Any]] = data["rows"]
    body = max(len(rows), 1) * ROW_H
    H = HEADER_H + 16 + body + 16 + (30 if data.get("more") else 0) + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    d.text((PAD, 34), data["title"], font=font("heavy", 44), fill=TEXT)
    d.text((PAD, 92), data["subtitle"], font=font("regular", 20), fill=MUTED)

    y = HEADER_H + 16
    if not rows:
        d.text((W // 2, y + 40), data.get("empty_message") or "예정된 경기가 없습니다.",
               font=font("regular", 24), fill=MUTED, anchor="mm")
    for i, r in enumerate(rows):
        top = y + i * ROW_H
        d.rounded_rectangle([PAD, top + 4, W - PAD, top + ROW_H - 4], radius=12, fill=PANEL if i % 2 == 0 else PANEL_2)
        cy = top + ROW_H // 2
        status = r["status"]
        # 시간 / 상태
        if status == "live":
            pill(d, (PAD + 14, cy - 15), "LIVE", LIVE, font("heavy", 18), h=30)
        else:
            d.text((PAD + 70, cy), r["time"], font=font("bold", 22), fill=MUTED if status == "completed" else TEXT, anchor="mm")
        # 팀1 | 스코어 | 팀2
        mid = 560
        paste_logo(img, logos.get(r.get("logo1")), (mid - 150, cy - 8), 38, r["team1"])
        n1, f1 = fit_text(d, r["team1"], "bold", 22, 130, 14)
        d.text((mid - 150, cy + 24), n1, font=f1, fill=TEXT, anchor="mm")
        paste_logo(img, logos.get(r.get("logo2")), (mid + 150, cy - 8), 38, r["team2"])
        n2, f2 = fit_text(d, r["team2"], "bold", 22, 130, 14)
        d.text((mid + 150, cy + 24), n2, font=f2, fill=TEXT, anchor="mm")
        if status == "upcoming" or r.get("score1") is None:
            d.text((mid, cy), "VS", font=font("heavy", 24), fill=MUTED, anchor="mm")
        else:
            s1, s2 = r["score1"], r["score2"]
            win1 = status == "completed" and s1 > s2
            win2 = status == "completed" and s2 > s1
            d.text((mid - 28, cy), str(s1), font=font("heavy", 34), fill=GREEN if win1 else TEXT, anchor="mm")
            d.text((mid, cy), ":", font=font("heavy", 28), fill=MUTED, anchor="mm")
            d.text((mid + 28, cy), str(s2), font=font("heavy", 34), fill=GREEN if win2 else TEXT, anchor="mm")
        # 대회
        ev = r.get("event") or ""
        if ev:
            e, ef = fit_text(d, ev, "regular", 16, 190, 12)
            d.text((W - PAD - 14, cy), e, font=ef, fill=MUTED, anchor="rm")

    y += body + 8
    if data.get("more"):
        d.text((W // 2, y + 10), data["more"], font=font("regular", 18), fill=MUTED, anchor="mm")
    d.text((W // 2, H - FOOTER_H // 2), data.get("footer", ""), font=font("regular", 16), fill=MUTED, anchor="mm")
    return to_png(img)
