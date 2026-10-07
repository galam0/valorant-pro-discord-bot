"""팀 맵 통계 이미지 카드 (VLR 팀 통계)."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import BG, GOLD, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT, fit_text, font, paste_logo, to_png

W = 1000
PAD = 30
HEADER_H = 150
ROW_H = 56
FOOTER_H = 52
MAP_KO = {"Bind": "바인드", "Haven": "헤이븐", "Split": "스플릿", "Ascent": "어센트", "Icebox": "아이스박스",
          "Breeze": "브리즈", "Fracture": "프랙처", "Pearl": "펄", "Lotus": "로터스", "Sunset": "선셋",
          "Abyss": "어비스", "Corrode": "코로드", "Summit": "서밋"}
COLS = [("경기", 330), ("승-패", 430), ("공격 승률", 760), ("수비 승률", 890)]   # 오른쪽 끝 x (승률 막대는 440~600)


def pct_color(p: int | None) -> tuple[int, int, int]:
    if p is None:
        return MUTED
    return GREEN if p >= 60 else (GOLD if p >= 50 else RED)


def team_maps_data(team_name: str, stats: list[Any], period_label: str, limit: int = 12) -> dict[str, Any]:
    rows = sorted(stats, key=lambda m: (-m.games, m.map_name))[:limit]
    return {
        "team": team_name, "period": period_label,
        "rows": [{
            "map": f"{MAP_KO.get(m.map_name, m.map_name)}", "games": m.games, "wl": f"{m.wins}-{m.losses}",
            "win": m.win_pct, "atk": m.atk_win_pct, "def": m.def_win_pct,
        } for m in rows],
        "best": max((m for m in stats if m.games >= 5 and m.win_pct is not None), key=lambda m: m.win_pct, default=None),
        "worst": min((m for m in stats if m.games >= 5 and m.win_pct is not None), key=lambda m: m.win_pct, default=None),
    }


def render_team_maps_card(data: dict[str, Any], images: dict[str, Any] | None = None) -> bytes:
    images = images or {}
    rows = data["rows"]
    H = HEADER_H + 50 + max(len(rows), 1) * ROW_H + 16 + FOOTER_H
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    paste_logo(img, images.get("team_logo"), (PAD + 55, HEADER_H // 2), 90, data["team"])
    name, nf = fit_text(d, data["team"], "heavy", 50, 560, 28)
    d.text((PAD + 130, 52), name, font=nf, fill=TEXT, anchor="lm")
    d.text((PAD + 130, 106), "맵 통계", font=font("bold", 24), fill=MUTED, anchor="lm")
    d.text((W - PAD, 40), data["period"], font=font("bold", 22), fill=RED, anchor="ra")

    y = HEADER_H + 14
    d.text((PAD + 14, y + 14), "맵", font=font("bold", 16), fill=MUTED, anchor="lm")
    d.text((520, y + 14), "승률", font=font("bold", 16), fill=MUTED, anchor="mm")
    for title, rx in COLS:
        d.text((rx, y + 14), title, font=font("bold", 16), fill=MUTED, anchor="rm")
    d.line([PAD, y + 34, W - PAD, y + 34], fill=LINE, width=2)
    y += 44
    if not rows:
        d.text((W // 2, y + 30), "표시할 맵 기록이 없습니다.", font=font("regular", 22), fill=MUTED, anchor="mm")
    for i, r in enumerate(rows):
        top = y + i * ROW_H
        cy = top + ROW_H // 2
        d.rounded_rectangle([PAD, top + 3, W - PAD, top + ROW_H - 3], radius=10, fill=PANEL if i % 2 == 0 else PANEL_2)
        d.text((PAD + 16, cy), r["map"], font=font("bold", 22), fill=TEXT, anchor="lm")
        d.text((330, cy), str(r["games"]), font=font("regular", 21), fill=TEXT, anchor="rm")
        d.text((430, cy), r["wl"], font=font("regular", 21), fill=TEXT, anchor="rm")
        w = r["win"]
        d.rounded_rectangle([450, cy - 9, 600, cy + 9], radius=8, fill=LINE)
        if w:
            d.rounded_rectangle([450, cy - 9, 450 + int(150 * w / 100), cy + 9], radius=8, fill=pct_color(w))
        d.text((612, cy), f"{w}%" if w is not None else "-", font=font("bold", 20), fill=pct_color(w), anchor="lm")
        for key, rx in (("atk", 760), ("def", 890)):
            v = r[key]
            d.text((rx, cy), f"{v}%" if v is not None else "-", font=font("regular", 21), fill=pct_color(v), anchor="rm")
    best, worst = data.get("best"), data.get("worst")
    foot = ""
    if best and worst and best is not worst:
        foot = f"강한 맵 {MAP_KO.get(best.map_name, best.map_name)} {best.win_pct}% · 약한 맵 {MAP_KO.get(worst.map_name, worst.map_name)} {worst.win_pct}%  (5경기 이상)  |  출처: VLR.gg"
    else:
        foot = "출처: VLR.gg"
    d.text((W // 2, H - FOOTER_H // 2), foot, font=font("regular", 16), fill=MUTED, anchor="mm")
    return to_png(img)
