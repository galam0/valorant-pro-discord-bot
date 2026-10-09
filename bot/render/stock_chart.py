"""/주식추이 차트: 종목별 최근 가격 흐름 (선 그래프). 한국식 색: 오르면 빨강, 내리면 파랑."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from bot.render.base import font

W, H = 800, 420
BG, STRIPE = (30, 42, 58), (36, 50, 69)
NAVY, WHITE, DIM, GRID = (27, 36, 51), (250, 247, 240), (150, 162, 178), (52, 68, 90)
UP, DOWN = (255, 90, 98), (96, 160, 255)
# 여러 종목을 겹쳐 그릴 때 쓰는 구분 색
PALETTE = [(255, 120, 130), (96, 160, 255), (255, 205, 80), (120, 226, 170), (190, 140, 255), (255, 160, 90)]


def render_stock_chart(series: dict[str, list[int]], title: str, *, single: bool) -> bytes:
    """series: {종목 이름: 가격들(오래된 것부터)}.
    single=True 면 가격(VP)을 그대로, False 면 처음 값을 0%로 맞춘 등락률(%)을 그린다."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for i in range(-H, W, 56):
        d.line([(i, H), (i + H, 0)], fill=STRIPE, width=18)
    d.rounded_rectangle([14, 14, W - 14, H - 14], radius=26, outline=NAVY, width=5)
    d.text((44, 46), title, font=font("heavy", 30), fill=WHITE, anchor="lm")

    data = {k: v for k, v in series.items() if len(v) >= 2}
    x0, x1, y0, y1 = 110, W - 44, 92, H - 96
    if not data:
        d.text((W // 2, H // 2), "아직 기록이 부족해요", font=font("bold", 26), fill=DIM, anchor="mm")
        out = BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    if single:
        lines = {k: [float(p) for p in v] for k, v in data.items()}
    else:
        lines = {k: [(p / v[0] - 1) * 100 for p in v] for k, v in data.items()}
    allv = [p for v in lines.values() for p in v]
    lo, hi = min(allv), max(allv)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad

    def y_of(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    for i in range(5):                                   # 가로 눈금
        v = lo + (hi - lo) * i / 4
        y = y_of(v)
        d.line([(x0, y), (x1, y)], fill=GRID, width=1)
        label = f"{v:,.0f}" if single else f"{v:+.1f}%"
        d.text((x0 - 12, y), label, font=font("regular", 15), fill=DIM, anchor="rm")
    if not single and lo < 0 < hi:                       # 0% 기준선
        d.line([(x0, y_of(0)), (x1, y_of(0))], fill=DIM, width=2)

    n_max = max(len(v) for v in lines.values())
    for idx, (name, vals) in enumerate(lines.items()):
        color = (UP if vals[-1] >= vals[0] else DOWN) if single else PALETTE[idx % len(PALETTE)]
        off = n_max - len(vals)
        pts = [(x0 + (x1 - x0) * (off + i) / max(n_max - 1, 1), y_of(v)) for i, v in enumerate(vals)]
        d.line(pts, fill=color, width=4, joint="curve")
        d.ellipse([pts[-1][0] - 5, pts[-1][1] - 5, pts[-1][0] + 5, pts[-1][1] + 5], fill=color)

    if single:
        name, vals = next(iter(data.items()))
        first, last = data[name][0], data[name][-1]
        pct = (last / first - 1) * 100
        d.text((x1, 46), f"{last:,} VP  {'▲' if pct >= 0 else '▼'} {abs(pct):.1f}%", font=font("heavy", 28),
               fill=UP if pct >= 0 else DOWN, anchor="rm")
    else:                                                # 범례
        lx = 44
        for idx, (name, vals) in enumerate(lines.items()):
            color = PALETTE[idx % len(PALETTE)]
            d.rounded_rectangle([lx, H - 72, lx + 16, H - 56], radius=4, fill=color)
            d.text((lx + 24, H - 64), name, font=font("bold", 17), fill=WHITE, anchor="lm")
            lx += 28 + int(d.textlength(name, font=font("bold", 17))) + 22
    d.text((W - 44, H - 34), f"최근 {n_max}번 변동 · 매시 정각 기준", font=font("regular", 15), fill=DIM, anchor="rm")
    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
