"""팀 랭킹 이미지 카드."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GOLD, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, to_png,
)

W = 1000
PAD = 30
HEADER_H = 130
ROW_H = 72
FOOTER_H = 52
MEDAL = {1: GOLD, 2: (192, 198, 206), 3: (205, 127, 50)}
LOSS = (237, 100, 110)


def render_ranking_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: {title, subtitle, rows: [{rank, name, rating, streak, country, logo_key}], footer}"""
    logos = logos or {}
    rows: list[dict[str, Any]] = data["rows"]
    H = HEADER_H + 16 + len(rows) * ROW_H + 16 + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    d.text((PAD, 34), data["title"], font=font("heavy", 44), fill=TEXT)
    d.text((PAD, 92), data["subtitle"], font=font("regular", 20), fill=MUTED)
    d.text((W - PAD, 56), "RATING", font=font("bold", 16), fill=MUTED, anchor="ra")

    y = HEADER_H + 16
    for i, r in enumerate(rows):
        top = y + i * ROW_H
        d.rounded_rectangle([PAD, top + 4, W - PAD, top + ROW_H - 4], radius=12, fill=PANEL if i % 2 == 0 else PANEL_2)
        cy = top + ROW_H // 2

        rank = r["rank"]
        color = MEDAL.get(rank, MUTED)
        if rank in MEDAL:
            d.ellipse([PAD + 14, cy - 18, PAD + 50, cy + 18], fill=color)
            d.text((PAD + 32, cy), str(rank), font=font("heavy", 22), fill=(20, 24, 30), anchor="mm")
        else:
            d.text((PAD + 32, cy), str(rank), font=font("bold", 24), fill=color, anchor="mm")

        paste_logo(img, logos.get(r.get("logo_key")), (PAD + 100, cy), 46, r["name"])

        name, nf = fit_text(d, r["name"], "bold", 27, 470, 18)
        d.text((PAD + 142, cy - (10 if r.get("country") else 0)), name, font=nf, fill=TEXT, anchor="lm")
        if r.get("country"):
            d.text((PAD + 142, cy + 17), r["country"], font=font("regular", 16), fill=MUTED, anchor="lm")

        streak = r.get("streak")
        if streak and abs(streak) >= 2:
            text = f"{streak}연승" if streak > 0 else f"{-streak}연패"
            col = GREEN if streak > 0 else LOSS
            f = font("bold", 18)
            tw = d.textlength(text, font=f) + 24
            x1 = W - PAD - 160
            d.rounded_rectangle([x1 - tw, cy - 15, x1, cy + 15], radius=15, outline=col, width=2)
            d.text((x1 - tw / 2, cy), text, font=f, fill=col, anchor="mm")

        rating = str(r["rating"]) if r.get("rating") is not None else "-"
        d.text((W - PAD - 24, cy), rating, font=font("heavy", 30), fill=GOLD if rank == 1 else TEXT, anchor="rm")

    fy = H - FOOTER_H
    d.line([PAD, fy, W - PAD, fy], fill=LINE, width=1)
    d.text((PAD, fy + FOOTER_H / 2), data["footer"], font=font("regular", 16), fill=MUTED, anchor="lm")
    return to_png(img)
