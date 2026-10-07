"""대진표(브래킷) 이미지 카드."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GOLD, GREEN, LINE, LIVE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, to_png,
)

MIN_W = 1100
PAD = 30
HEADER_H = 150
BOX_W = 230
BOX_H = 64
GAP = 46
SLOT = 100          # 첫 번째 열에서 경기 하나가 차지하는 세로 칸
LABEL_H = 36
SECTION_TITLE_H = 56
FOOTER_H = 52
SECTION_TITLE = {"upper": "승자조", "lower": "패자조", "main": "대진표"}


def _section_height(sec: dict[str, Any]) -> int:
    most = max(len(c["matches"]) for c in sec["columns"])
    return SECTION_TITLE_H + LABEL_H + most * SLOT + 10


def _team_row(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, team: dict[str, Any],
              logos: dict[str, Any], top: bool) -> None:
    h = BOX_H // 2
    cy = y + h // 2
    tbd = not team.get("name")
    winner, loser = team.get("winner"), team.get("loser")
    if winner:
        d.rectangle([x + 2, y + (2 if top else 0), x + 5, y + h - (0 if top else 2)], fill=GREEN)
    if tbd:
        d.text((x + 14, cy), "미정", font=font("regular", 16), fill=MUTED, anchor="lm")
    else:
        paste_logo(img, logos.get(team.get("logo_key")), (x + 24, cy), 22, team["name"])
        color = MUTED if loser else TEXT
        name, nf = fit_text(d, team["name"], "bold" if not loser else "regular", 16, BOX_W - 100, 11)
        d.text((x + 42, cy), name, font=nf, fill=color, anchor="lm")
    if team.get("score") is not None:
        d.text((x + BOX_W - 14, cy), str(team["score"]), font=font("heavy", 21),
               fill=GOLD if winner else MUTED, anchor="rm")


def render_bracket_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: {title, subtitle, sections:[{kind, columns:[{label, matches:[{t1,t2,when,live}]}]}], footer}"""
    logos = logos or {}
    sections: list[dict[str, Any]] = data["sections"]
    ncols = max(len(s["columns"]) for s in sections)
    W = max(MIN_W, PAD * 2 + ncols * BOX_W + (ncols - 1) * GAP)
    H = HEADER_H + 16 + sum(_section_height(s) for s in sections) + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    paste_logo(img, logos.get("event"), (PAD + 55, HEADER_H // 2 - 2), 96, data["title"])
    title, tf = fit_text(d, data["title"], "heavy", 44, W - PAD * 2 - 140, 26)
    d.text((PAD + 130, 44), title, font=tf, fill=TEXT)
    d.text((PAD + 130, 100), data["subtitle"], font=font("regular", 20), fill=MUTED)

    y = HEADER_H + 16
    for sec in sections:
        cols = sec["columns"]
        most = max(len(c["matches"]) for c in cols)
        body_h = most * SLOT
        d.text((PAD, y + 8), SECTION_TITLE.get(sec["kind"], "대진표"), font=font("heavy", 26), fill=TEXT)
        d.line([PAD, y + SECTION_TITLE_H - 8, W - PAD, y + SECTION_TITLE_H - 8], fill=LINE, width=1)
        top = y + SECTION_TITLE_H + LABEL_H

        centers: list[list[int]] = []
        for ci, col in enumerate(cols):
            n = len(col["matches"])
            centers.append([int(top + (i + 0.5) * body_h / n) for i in range(n)])

        # 연결선 (경기 → 다음 라운드)
        for ci in range(len(cols) - 1):
            n, nn = len(cols[ci]["matches"]), len(cols[ci + 1]["matches"])
            x0 = PAD + ci * (BOX_W + GAP) + BOX_W
            x1 = x0 + GAP
            xm = x0 + GAP // 2
            for i, cy in enumerate(centers[ci]):
                if nn == n:
                    d.line([x0, cy, x1, cy], fill=LINE, width=2)
                elif nn * 2 == n:
                    py = centers[ci + 1][i // 2]
                    d.line([x0, cy, xm, cy], fill=LINE, width=2)
                    d.line([xm, cy, xm, py], fill=LINE, width=2)
                    d.line([xm, py, x1, py], fill=LINE, width=2)

        for ci, col in enumerate(cols):
            x = PAD + ci * (BOX_W + GAP)
            label, lf = fit_text(d, col["label"], "bold", 18, BOX_W, 12)
            d.text((x + BOX_W / 2, y + SECTION_TITLE_H + LABEL_H / 2), label, font=lf, fill=MUTED, anchor="mm")
            for m, cy in zip(col["matches"], centers[ci]):
                by = cy - BOX_H // 2
                outline = LIVE if m.get("live") else LINE
                d.rounded_rectangle([x, by, x + BOX_W, by + BOX_H], radius=10, fill=PANEL,
                                    outline=outline, width=2 if m.get("live") else 1)
                _team_row(img, d, x, by, m["t1"], logos, True)
                d.line([x + 8, by + BOX_H // 2, x + BOX_W - 8, by + BOX_H // 2], fill=LINE, width=1)
                _team_row(img, d, x, by + BOX_H // 2, m["t2"], logos, False)
                if m.get("live"):
                    d.rounded_rectangle([x + BOX_W - 56, by + BOX_H + 4, x + BOX_W, by + BOX_H + 22], radius=9, fill=LIVE)
                    d.text((x + BOX_W - 28, by + BOX_H + 13), "LIVE", font=font("heavy", 12), fill=(255, 255, 255), anchor="mm")
                elif m.get("when"):
                    d.text((x + BOX_W / 2, by + BOX_H + 14), m["when"], font=font("regular", 14), fill=MUTED, anchor="mm")
        y += _section_height(sec)

    fy = H - FOOTER_H
    d.line([PAD, fy, W - PAD, fy], fill=LINE, width=1)
    d.text((PAD, fy + FOOTER_H / 2), data["footer"], font=font("regular", 16), fill=MUTED, anchor="lm")
    return to_png(img)
