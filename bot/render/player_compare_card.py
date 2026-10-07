"""두 선수 통계 비교 이미지 카드 (VLR 요원별 통계를 라운드 가중 평균한 값)."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, to_png,
)
from bot.render.player_stats_card import TIMESPAN_KO, country_ko

W = 1000
PAD = 30
HEADER_H = 250
ROW_H = 62
FOOTER_H = 70
MID = W // 2
COLORS = ((88, 166, 255), (255, 70, 85))   # 왼쪽 파랑 / 오른쪽 레드

# (제목, summary 키, 소수 자릿수, 접미사, 높을수록 좋은가)
METRICS: list[tuple[str, str, int, str, bool]] = [
    ("레이팅", "rating", 2, "", True),
    ("ACS", "acs", 1, "", True),
    ("K:D", "kd", 2, "", True),
    ("KAST", "kast", 0, "%", True),
    ("ADR", "adr", 1, "", True),
    ("라운드당 킬", "kpr", 2, "", True),
    ("라운드당 퍼스트 킬", "fkpr", 2, "", True),
    ("총 킬", "kills", 0, "", True),
    ("총 데스", "deaths", 0, "", False),
    ("총 어시스트", "assists", 0, "", True),
    ("라운드 수", "rounds", 0, "", True),
]


def summarize(page: Any) -> dict[str, float | None]:
    """요원별 통계 → 라운드 가중 평균(비율형)과 합계(누적형)."""
    agents = list(page.agents)

    def wavg(attr: str) -> float | None:
        pairs = [(getattr(a, attr), a.rounds or 0) for a in agents if getattr(a, attr) is not None and a.rounds]
        total = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total if total else None

    def total(attr: str) -> float | None:
        vals = [getattr(a, attr) for a in agents if getattr(a, attr) is not None]
        return float(sum(vals)) if vals else None

    return {
        "rating": wavg("rating"), "acs": wavg("acs"), "kd": wavg("kd"), "kast": wavg("kast"),
        "adr": wavg("adr"), "kpr": wavg("kpr"), "fkpr": wavg("fkpr"),
        "kills": total("kills"), "deaths": total("deaths"), "assists": total("assists"),
        "rounds": total("rounds"),
    }


def compare_data(a: Any, b: Any) -> dict[str, Any]:
    def side(page: Any) -> dict[str, Any]:
        top = [x.agent.capitalize() for x in sorted(page.agents, key=lambda x: -(x.rounds or 0))[:3]]
        return {
            "nickname": page.nickname, "real_name": page.real_name, "team": page.team_name,
            "country": country_ko(page.country_code, page.country_name) if (page.country_code or page.country_name) else None,
            "stats": summarize(page), "top_agents": top, "has_data": bool(page.agents),
        }

    return {
        "a": side(a), "b": side(b),
        "timespan_label": TIMESPAN_KO.get(a.timespan, a.timespan) if a.timespan == b.timespan
        else f"{TIMESPAN_KO.get(a.timespan, a.timespan)} / {TIMESPAN_KO.get(b.timespan, b.timespan)}",
        "footer": "출처: VLR.gg · 요원별 통계를 라운드 수로 가중 평균 · 초록색이 더 좋은 쪽",
    }


def _fmt(v: float | None, nd: int, suffix: str) -> str:
    return "-" if v is None else (f"{v:,.{nd}f}{suffix}" if nd else f"{v:,.0f}{suffix}")


def render_player_compare_card(data: dict[str, Any], images: dict[str, Any] | None = None) -> bytes:
    images = images or {}
    H = HEADER_H + 20 + len(METRICS) * ROW_H + 20 + 70 + FOOTER_H
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    for i, key in enumerate(("a", "b")):
        side = data[key]
        cx = 250 if i == 0 else W - 250
        photo = images.get(f"photo{i}")
        if photo is not None:
            p = photo.convert("RGBA")
            p.thumbnail((120, 120), Image.LANCZOS)
            img.paste(p, (cx - p.width // 2, 22), p)
        else:
            paste_logo(img, None, (cx, 82), 110, side["nickname"])
        name, nf = fit_text(d, side["nickname"], "heavy", 40, 400, 24)
        d.text((cx, 164), name, font=nf, fill=COLORS[i], anchor="mm")
        sub = " · ".join(v for v in (side.get("team"), side.get("country")) if v)
        if sub:
            s, sf = fit_text(d, sub, "regular", 20, 400, 14)
            d.text((cx, 198), s, font=sf, fill=MUTED, anchor="mm")
        if side.get("real_name"):
            r, rf = fit_text(d, side["real_name"], "regular", 16, 400, 12)
            d.text((cx, 224), r, font=rf, fill=MUTED, anchor="mm")
    d.text((MID, 100), "VS", font=font("heavy", 54), fill=TEXT, anchor="mm")
    d.text((MID, 160), data["timespan_label"], font=font("bold", 18), fill=RED, anchor="mm")

    y = HEADER_H + 20
    for i, (title, key, nd, suffix, higher_better) in enumerate(METRICS):
        top = y + i * ROW_H
        d.rounded_rectangle([PAD, top + 3, W - PAD, top + ROW_H - 3], radius=10, fill=PANEL if i % 2 == 0 else PANEL_2)
        cy = top + ROW_H // 2
        va, vb = data["a"]["stats"].get(key), data["b"]["stats"].get(key)
        win = None
        if va is not None and vb is not None and round(va, nd) != round(vb, nd):
            win = 0 if (va > vb) == higher_better else 1
        for side, v, x, anchor in ((0, va, PAD + 40, "lm"), (1, vb, W - PAD - 40, "rm")):
            d.text((x, cy), _fmt(v, nd, suffix), font=font("heavy" if win == side else "bold", 28),
                   fill=GREEN if win == side else TEXT, anchor=anchor)
        d.text((MID, cy), title, font=font("regular", 20), fill=MUTED, anchor="mm")

    y2 = y + len(METRICS) * ROW_H + 20
    for i, key in enumerate(("a", "b")):
        agents = data[key]["top_agents"]
        text = "주력 요원  " + (" · ".join(agents) if agents else "-")
        d.text((250 if i == 0 else W - 250, y2 + 20), text, font=font("bold", 20), fill=COLORS[i], anchor="mm")
    d.text((W // 2, H - FOOTER_H // 2), data["footer"], font=font("regular", 15), fill=MUTED, anchor="mm")
    return to_png(img)
