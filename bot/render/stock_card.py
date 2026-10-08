"""/주식 시세판 카드 (플랫 스타일). 한국식 색: 오르면 빨강, 내리면 파랑."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from bot.render.base import fit_text, font

W = 800
ROW_H = 74
TOP = 78
BG, STRIPE, CARD = (30, 42, 58), (36, 50, 69), (24, 33, 47)
NAVY, WHITE, DIM = (27, 36, 51), (250, 247, 240), (150, 162, 178)
UP, DOWN, FLAT = (255, 90, 98), (96, 160, 255), (190, 198, 210)
ACCENT = (192, 255, 238)


def _spark(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], values: list[int], color) -> None:
    x0, y0, x1, y1 = box
    if len(values) < 2:
        d.line([(x0, (y0 + y1) // 2), (x1, (y0 + y1) // 2)], fill=color, width=3)
        return
    lo, hi = min(values), max(values)
    span = max(hi - lo, 1)
    pts = [(x0 + (x1 - x0) * i / (len(values) - 1), y1 - (y1 - y0) * (v - lo) / span) for i, v in enumerate(values)]
    d.line(pts, fill=color, width=3, joint="curve")
    d.ellipse([pts[-1][0] - 4, pts[-1][1] - 4, pts[-1][0] + 4, pts[-1][1] + 4], fill=color)


def render_stock_board(quotes: list) -> bytes:
    """quotes: Quote(symbol, name, price, change_pct, spark) 목록."""
    h = TOP + ROW_H * len(quotes) + 26
    img = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(img)
    for i in range(-h, W, 56):
        d.line([(i, h), (i + h, 0)], fill=STRIPE, width=18)
    d.rounded_rectangle([14, 14, W - 14, h - 14], radius=26, outline=NAVY, width=5)
    d.text((44, 46), "VP 주식 시세판", font=font("heavy", 30), fill=WHITE, anchor="lm")
    d.text((W - 44, 46), "24시간 대비", font=font("regular", 16), fill=DIM, anchor="rm")
    for i, q in enumerate(quotes):
        y = TOP + ROW_H * i
        d.rounded_rectangle([34, y, W - 34, y + ROW_H - 10], radius=18, fill=CARD)
        d.rounded_rectangle([48, y + 16, 118, y + 46], radius=15, fill=ACCENT)
        d.text((83, y + 31), q.symbol, font=font("heavy", 18), fill=NAVY, anchor="mm")
        name, nf = fit_text(d, q.name, "bold", 20, 230, 14)
        d.text((136, y + 31), name, font=nf, fill=WHITE, anchor="lm")
        ch = q.change_pct
        color = FLAT if ch is None or abs(ch) < 0.05 else (UP if ch > 0 else DOWN)
        arrow = "–" if color == FLAT else ("▲" if ch > 0 else "▼")
        _spark(d, (400, y + 14, 520, y + 46), q.spark, color)
        d.text((W - 54, y + 22), f"{q.price:,} VP", font=font("heavy", 24), fill=WHITE, anchor="rm")
        txt = "-" if ch is None else f"{arrow} {abs(ch):.1f}%"
        d.text((W - 54, y + 46), txt, font=font("bold", 16), fill=color, anchor="rm")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
