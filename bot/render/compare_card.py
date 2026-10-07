"""두 팀 비교 이미지 카드."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GOLD, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, to_png,
)

W = 1000
PAD = 30
HEADER_H = 250
ROW_H = 78
LOSS = (237, 100, 110)
COL_W = (W - PAD * 2 - 140) // 2        # 양쪽 열 너비 (가운데 140px은 항목 이름)
LX = PAD + COL_W // 2                    # 왼쪽 열 중심
RX = W - PAD - COL_W // 2                # 오른쪽 열 중심
MX = W // 2


def _form_pills(d: ImageDraw.ImageDraw, cx: int, cy: int, results: list[str]) -> None:
    size, gap = 34, 8
    total = len(results) * size + (len(results) - 1) * gap
    x = cx - total / 2
    for r in results:
        col = GREEN if r == "W" else LOSS if r == "L" else MUTED
        d.rounded_rectangle([x, cy - size / 2, x + size, cy + size / 2], radius=8, fill=col)
        d.text((x + size / 2, cy), r, font=font("heavy", 18), fill=(15, 25, 35), anchor="mm")
        x += size + gap


def render_compare_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: {a:{name,country,region,form:[W/L],roster:[이름]}, b:{...}, h2h:{a_wins,b_wins,rows:[{...}]}, footer}"""
    logos = logos or {}
    a, b, h2h = data["a"], data["b"], data["h2h"]
    rows = [("국가", "text"), ("최근 5경기", "form"), ("로스터", "roster"), ("맞대결", "h2h")]
    h2h_rows = h2h.get("rows") or []
    h2h_extra = len(h2h_rows) * 40 + (16 if h2h_rows else 0)
    H = HEADER_H + 16 + len(rows) * ROW_H + h2h_extra + 70

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # --- 머리: 로고 + 팀명 + VS ---
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    for cx, team, key in ((LX, a, "a"), (RX, b, "b")):
        paste_logo(img, logos.get(key), (cx, 100), 130, team["name"])
        name, nf = fit_text(d, team["name"], "heavy", 30, COL_W - 10, 18)
        d.text((cx, 197), name, font=nf, fill=TEXT, anchor="mm")
    d.text((MX, 100), "VS", font=font("heavy", 46), fill=RED, anchor="mm")

    y = HEADER_H + 16
    for i, (label, kind) in enumerate(rows):
        top = y
        extra = h2h_extra if kind == "h2h" else 0
        h = ROW_H + extra
        d.rounded_rectangle([PAD, top + 4, W - PAD, top + h - 4], radius=12, fill=PANEL if i % 2 == 0 else PANEL_2)
        cy = top + ROW_H // 2
        d.text((MX, cy), label, font=font("bold", 18), fill=MUTED, anchor="mm")

        for cx, team in ((LX, a), (RX, b)):
            if kind == "text":
                v, vf = fit_text(d, team.get("country") or "-", "bold", 24, COL_W - 20, 16)
                d.text((cx, cy), v, font=vf, fill=TEXT, anchor="mm")
            elif kind == "form":
                form = team.get("form") or []
                if form:
                    _form_pills(d, cx, cy - 10, form)
                    wins = form.count("W")
                    d.text((cx, cy + 22), f"{wins}승 {len(form) - wins}패", font=font("regular", 15), fill=MUTED, anchor="mm")
                else:
                    d.text((cx, cy), "기록 없음", font=font("regular", 18), fill=MUTED, anchor="mm")
            elif kind == "roster":
                names = team.get("roster") or []
                line1 = " · ".join(names[:3]) or "-"
                line2 = " · ".join(names[3:])
                t1, f1 = fit_text(d, line1, "bold", 20, COL_W - 16, 14)
                d.text((cx, cy - (12 if line2 else 0)), t1, font=f1, fill=TEXT, anchor="mm")
                if line2:
                    t2, f2 = fit_text(d, line2, "bold", 20, COL_W - 16, 14)
                    d.text((cx, cy + 14), t2, font=f2, fill=TEXT, anchor="mm")
            elif kind == "h2h":
                wins = h2h["a_wins"] if team is a else h2h["b_wins"]
                lead = h2h["a_wins"] > h2h["b_wins"] if team is a else h2h["b_wins"] > h2h["a_wins"]
                d.text((cx, cy), f"{wins}승", font=font("heavy", 34), fill=GOLD if lead else TEXT, anchor="mm")

        if kind == "h2h":
            if not h2h_rows:
                d.text((MX, cy + 34), "저장된 맞대결 기록이 없습니다", font=font("regular", 16), fill=MUTED, anchor="mm")
            ry = top + ROW_H + 6
            for r in h2h_rows:
                d.line([PAD + 20, ry - 4, W - PAD - 20, ry - 4], fill=LINE, width=1)
                d.text((PAD + 24, ry + 16), r["date"], font=font("regular", 16), fill=MUTED, anchor="lm")
                col_a = GREEN if r["winner"] == "a" else MUTED
                col_b = GREEN if r["winner"] == "b" else MUTED
                d.text((MX - 14, ry + 16), str(r["score_a"]), font=font("heavy", 22), fill=col_a, anchor="rm")
                d.text((MX, ry + 16), ":", font=font("bold", 20), fill=MUTED, anchor="mm")
                d.text((MX + 14, ry + 16), str(r["score_b"]), font=font("heavy", 22), fill=col_b, anchor="lm")
                ev, ef = fit_text(d, r["event"] or "", "regular", 15, 330, 11)
                d.text((W - PAD - 24, ry + 16), ev, font=ef, fill=MUTED, anchor="rm")
                ry += 40
        y += h

    fy = H - 52
    d.line([PAD, fy, W - PAD, fy], fill=LINE, width=1)
    d.text((PAD, fy + 26), data["footer"], font=font("regular", 15), fill=MUTED, anchor="lm")
    return to_png(img)
