"""선수 통계 이미지 카드 (VLR 요원별 통계)."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.utils.korean import country_ko
from bot.render.base import (
    BG, GOLD, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, to_png,
)

W = 1000
PAD = 30
HEADER_H = 190
SUMMARY_H = 120
ROW_H = 58
FOOTER_H = 52
COLS = [  # (제목, 키, 오른쪽 끝 x)
    ("사용", "use", 330), ("라운드", "rounds", 420), ("레이팅", "rating", 520), ("ACS", "acs", 610),
    ("K:D", "kd", 690), ("KAST", "kast", 780), ("ADR", "adr", 870), ("KPR", "kpr", 960),
]


def _rating_color(r: float | None) -> tuple[int, int, int]:
    if r is None:
        return TEXT
    return GREEN if r >= 1.10 else (GOLD if r >= 1.0 else TEXT)


def render_player_stats_card(data: dict[str, Any], images: dict[str, Any] | None = None) -> bytes:
    """data: {nickname, real_name, country, team, timespan_label, summary:{...}, rows:[{agent, use, rounds,
    rating, acs, kd, kast, adr, kpr}], empty_message, footer}"""
    images = images or {}
    rows: list[dict[str, Any]] = data["rows"]
    body = max(len(rows), 1) * ROW_H + 50
    H = HEADER_H + (SUMMARY_H if rows else 0) + 20 + body + 16 + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    photo = images.get("photo")
    if photo is not None:
        p = photo.convert("RGBA")
        p.thumbnail((140, 140), Image.LANCZOS)
        img.paste(p, (PAD, 25), p)
    else:
        paste_logo(img, None, (PAD + 70, 95), 130, data["nickname"])
    x = PAD + 165
    name, nf = fit_text(d, data["nickname"], "heavy", 54, 520, 30)
    d.text((x, 30), name, font=nf, fill=TEXT)
    sub = " · ".join(v for v in (data.get("real_name"), data.get("country")) if v)
    if sub:
        d.text((x, 100), sub, font=font("regular", 20), fill=MUTED)
    if data.get("team"):
        paste_logo(img, images.get("team_logo"), (x + 22, 150), 36, data["team"])
        d.text((x + 52, 150), data["team"], font=font("bold", 22), fill=TEXT, anchor="lm")
    d.text((W - PAD, 40), data["timespan_label"], font=font("bold", 22), fill=RED, anchor="ra")

    y = HEADER_H + 16
    if rows:
        s = data["summary"]
        cells = [("레이팅", s["rating"]), ("ACS", s["acs"]), ("K:D", s["kd"]), ("KAST", s["kast"]),
                 ("ADR", s["adr"]), ("킬/데스/어시", s["kda"])]
        cw = (W - PAD * 2) / len(cells)
        d.rounded_rectangle([PAD, y, W - PAD, y + SUMMARY_H - 16], radius=14, fill=PANEL_2)
        for i, (label, val) in enumerate(cells):
            cx = PAD + cw * i + cw / 2
            color = _rating_color(s.get("rating_raw")) if label == "레이팅" else TEXT
            v, vf = fit_text(d, str(val), "heavy", 32, cw - 12, 18)
            d.text((cx, y + 38), v, font=vf, fill=color, anchor="mm")
            d.text((cx, y + 72), label, font=font("regular", 16), fill=MUTED, anchor="mm")
        y += SUMMARY_H

    y += 4
    d.text((PAD + 14, y + 14), "요원", font=font("bold", 16), fill=MUTED, anchor="lm")
    for title, _, rx in COLS:
        d.text((rx, y + 14), title, font=font("bold", 16), fill=MUTED, anchor="rm")
    d.line([PAD, y + 34, W - PAD, y + 34], fill=LINE, width=2)
    y += 44

    if not rows:
        d.text((W // 2, y + 30), data.get("empty_message") or "표시할 통계가 없습니다.",
               font=font("regular", 22), fill=MUTED, anchor="mm")
    for i, r in enumerate(rows):
        top = y + i * ROW_H
        d.rounded_rectangle([PAD, top + 3, W - PAD, top + ROW_H - 3], radius=10, fill=PANEL if i % 2 == 0 else PANEL_2)
        cy = top + ROW_H // 2
        icon = images.get(f"agent{i}")
        if icon is not None:
            paste_logo(img, icon, (PAD + 36, cy), 40, r["agent"])
        d.text((PAD + 70, cy), r["agent"], font=font("bold", 22), fill=TEXT, anchor="lm")
        for _, key, rx in COLS:
            color = _rating_color(r.get("rating_raw")) if key == "rating" else TEXT
            d.text((rx, cy), str(r.get(key, "-")), font=font("bold" if key == "rating" else "regular", 21),
                   fill=color, anchor="rm")

    d.text((W // 2, H - FOOTER_H // 2), data.get("footer", ""), font=font("regular", 16), fill=MUTED, anchor="mm")
    return to_png(img)


TIMESPAN_KO = {"30d": "최근 30일", "60d": "최근 60일", "90d": "최근 90일", "all": "전체 기간"}


def player_stats_data(page: Any) -> dict[str, Any]:
    """PlayerStatsPage → 카드 데이터. 요약은 라운드 수로 가중 평균한다."""
    agents = list(page.agents)

    def wavg(attr: str) -> float | None:
        pairs = [(getattr(a, attr), a.rounds or 0) for a in agents if getattr(a, attr) is not None and a.rounds]
        total = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total if total else None

    def f(v: float | None, nd: int = 2, suffix: str = "") -> str:
        return "-" if v is None else f"{v:.{nd}f}{suffix}"

    k = sum(a.kills or 0 for a in agents)
    dth = sum(a.deaths or 0 for a in agents)
    ast = sum(a.assists or 0 for a in agents)
    rating = wavg("rating")
    rows = [
        {"agent": a.agent.capitalize(),
         "use": f"{a.uses}회 ({a.use_pct}%)" if a.uses is not None and a.use_pct is not None else "-",
         "rounds": a.rounds if a.rounds is not None else "-",
         "rating": f(a.rating), "rating_raw": a.rating, "acs": f(a.acs, 1), "kd": f(a.kd),
         "kast": f(a.kast, 0, "%") if a.kast is not None else "-", "adr": f(a.adr, 1), "kpr": f(a.kpr)}
        for a in agents
    ]
    return {
        "nickname": page.nickname, "real_name": page.real_name,
        "country": country_ko(page.country_code, page.country_name) if (page.country_code or page.country_name) else None,
        "team": page.team_name,
        "timespan_label": TIMESPAN_KO.get(page.timespan, page.timespan),
        "summary": {"rating": f(rating), "rating_raw": rating, "acs": f(wavg("acs"), 1),
                    "kd": f(wavg("kd")), "kast": f(wavg("kast"), 0, "%"), "adr": f(wavg("adr"), 1),
                    "kda": f"{k}/{dth}/{ast}"},
        "rows": rows,
        "empty_message": "이 기간에는 표시할 통계가 없습니다.",
        "footer": "출처: VLR.gg · 요원별 통계 (라운드 가중 평균)",
    }
