"""경기 상세 이미지 카드: 스코어, 맵, 팀별 선수 스탯표."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GOLD, GREEN, LINE, LIVE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, pill, text_w, to_png,
)

W = 1100
PAD = 30

# (머리글, 키, 열 너비)
COLUMNS: list[tuple[str, str, int]] = [
    ("ACS", "acs", 72),
    ("K", "kills", 58),
    ("D", "deaths", 58),
    ("A", "assists", 58),
    ("+/-", "kd_diff", 66),
    ("KAST", "kast", 78),
    ("ADR", "adr", 70),
    ("HS%", "hs", 74),
    ("FK", "fk", 56),
]
NAME_X = PAD + 20
AGENT_X = 300
STAT_X = 1070 - sum(c[2] for c in COLUMNS)

HEADER_H = 260
MAPS_H = 96
TEAM_HEAD_H = 50
COL_HEAD_H = 36
ROW_H = 50
FOOTER_H = 56


def _num(v: Any) -> float:
    try:
        return float(str(v).replace("%", "").replace("+", ""))
    except (TypeError, ValueError):
        return -999.0


def _draw_header(img: Image.Image, d: ImageDraw.ImageDraw, data: dict[str, Any], logos: dict[str, Any]) -> None:
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED if data["status"] == "live" else LINE)

    # 대회 / 단계
    x = PAD
    if logos.get("event") is not None:
        paste_logo(img, logos["event"], (PAD + 18, 36), 36)
        x += 46
    event_text, ef = fit_text(d, data.get("event") or "", "bold", 22, 640)
    d.text((x, 22), event_text, font=ef, fill=TEXT)
    sub = " · ".join(s for s in (data.get("stage"), data.get("best_of")) if s)
    d.text((x, 52), sub, font=font("regular", 18), fill=MUTED)

    # 상태 배지
    status = data["status"]
    if status == "live":
        label, color = "● LIVE", LIVE
    elif status == "completed":
        label, color = "경기 종료", (58, 74, 90)
    else:
        label, color = "예정", (58, 74, 90)
    pf = font("bold", 20)
    pw = text_w(d, label, pf) + 28
    pill(d, (W - PAD - pw, 24), label, color, pf)
    if data.get("when"):
        d.text((W - PAD, 70), data["when"], font=font("regular", 17), fill=MUTED, anchor="ra")

    # 팀 / 스코어
    cy = 158
    for side, cx in (("team1", 230), ("team2", W - 230)):
        paste_logo(img, logos.get(side), (cx, cy - 18), 100, data[side])
        name, nf = fit_text(d, data[side], "heavy", 30, 300, 18)
        d.text((cx, cy + 52), name, font=nf, fill=TEXT, anchor="mm")

    s1, s2 = data.get("score1"), data.get("score2")
    if status == "upcoming" or s1 is None or s2 is None:
        d.text((W / 2, cy - 10), "VS", font=font("heavy", 64), fill=MUTED, anchor="mm")
    else:
        big = font("heavy", 92)
        c1 = TEXT if s1 >= s2 else MUTED
        c2 = TEXT if s2 >= s1 else MUTED
        d.text((W / 2 - 34, cy - 14), str(s1), font=big, fill=c1, anchor="rm")
        d.text((W / 2, cy - 18), ":", font=big, fill=MUTED, anchor="mm")
        d.text((W / 2 + 34, cy - 14), str(s2), font=big, fill=c2, anchor="lm")


def _draw_maps(d: ImageDraw.ImageDraw, data: dict[str, Any], top: int) -> None:
    maps = data.get("maps") or []
    if not maps:
        return
    gap = 14
    n = len(maps)
    cw = (W - PAD * 2 - gap * (n - 1)) / n
    for i, m in enumerate(maps):
        x0 = PAD + i * (cw + gap)
        y0, y1 = top + 18, top + MAPS_H - 8
        selected = m["game_id"] == data.get("selected")
        d.rounded_rectangle([x0, y0, x0 + cw, y1], radius=12, fill=PANEL_2 if selected else PANEL,
                            outline=RED if selected else LINE, width=3 if selected else 1)
        d.text((x0 + 18, y0 + 14), f"{m['order']}", font=font("heavy", 20), fill=MUTED)
        name, nf = fit_text(d, m["name"], "bold", 22, cw * 0.45)
        d.text((x0 + 44, y0 + 12), name, font=nf, fill=TEXT)

        if m["status"] == "upcoming":
            d.text((x0 + 44, y0 + 44), "미진행", font=font("regular", 17), fill=MUTED)
            continue
        s1, s2 = m.get("team1_score") or 0, m.get("team2_score") or 0
        if m["status"] == "live":
            d.ellipse([x0 + 44, y0 + 50, x0 + 56, y0 + 62], fill=LIVE)
            d.text((x0 + 64, y0 + 44), "진행 중", font=font("bold", 17), fill=LIVE)
        else:
            winner = data["team1"] if s1 > s2 else data["team2"] if s2 > s1 else ""
            win_txt, wf = fit_text(d, f"{winner} 승", "regular", 17, cw * 0.5)
            d.text((x0 + 44, y0 + 44), win_txt, font=wf, fill=GREEN)
        sf = font("heavy", 30)
        d.text((x0 + cw - 18, (y0 + y1) / 2), f"{s1} : {s2}", font=sf, fill=TEXT, anchor="rm")


def _draw_team_table(d: ImageDraw.ImageDraw, team: str, players: list[dict[str, Any]], top: int,
                     map_score: str | None, mvp: str | None, map_title: str = "") -> int:
    # 팀 머리줄: 팀명 · 맵 이름 ............ 맵 점수
    d.rounded_rectangle([PAD, top, W - PAD, top + TEAM_HEAD_H], radius=10, fill=PANEL_2)
    tf = font("heavy", 24)
    d.text((NAME_X, top + TEAM_HEAD_H / 2), team, font=tf, fill=TEXT, anchor="lm")
    if map_title:
        d.text((NAME_X + text_w(d, team, tf) + 14, top + TEAM_HEAD_H / 2), f"·  {map_title}",
               font=font("regular", 19), fill=MUTED, anchor="lm")
    if map_score:
        d.text((W - PAD - 20, top + TEAM_HEAD_H / 2), map_score, font=font("heavy", 24), fill=TEXT, anchor="rm")
    y = top + TEAM_HEAD_H

    # 열 머리글
    hf = font("bold", 17)
    d.text((NAME_X, y + COL_HEAD_H / 2), "선수", font=hf, fill=MUTED, anchor="lm")
    d.text((AGENT_X, y + COL_HEAD_H / 2), "요원", font=hf, fill=MUTED, anchor="lm")
    x = STAT_X
    for label, _, w in COLUMNS:
        d.text((x + w / 2, y + COL_HEAD_H / 2), label, font=hf, fill=MUTED, anchor="mm")
        x += w
    y += COL_HEAD_H

    rows = sorted(players, key=lambda p: _num(p.get("acs")), reverse=True)
    for i, p in enumerate(rows):
        if i % 2 == 0:
            d.rectangle([PAD, y, W - PAD, y + ROW_H], fill=PANEL)
        cy = y + ROW_H / 2
        is_mvp = mvp is not None and p.get("name") == mvp
        name, nf = fit_text(d, p.get("name") or "?", "bold", 22, AGENT_X - NAME_X - 40)
        d.text((NAME_X, cy), name, font=nf, fill=GOLD if is_mvp else TEXT, anchor="lm")
        if is_mvp:
            d.text((NAME_X + text_w(d, name, nf) + 10, cy), "MVP", font=font("heavy", 14), fill=GOLD, anchor="lm")
        agents = ", ".join(a for a in (p.get("agents") or []) if a) or "-"
        agent, af = fit_text(d, agents, "regular", 18, STAT_X - AGENT_X - 12)
        d.text((AGENT_X, cy), agent, font=af, fill=MUTED, anchor="lm")

        x = STAT_X
        vf = font("bold", 21)
        for _, key, w in COLUMNS:
            val = p.get(key)
            text = str(val) if val not in (None, "") else "-"
            color = TEXT
            if key == "kd_diff" and text != "-":
                n = _num(text)
                color = GREEN if n > 0 else RED if n < 0 else MUTED
                if n > 0 and not text.startswith("+"):
                    text = "+" + text
            elif text == "-":
                color = MUTED
            d.text((x + w / 2, cy), text, font=vf, fill=color, anchor="mm")
            x += w
        y += ROW_H
    return y


def render_match_card(data: dict[str, Any], logos: dict[str, Any] | None = None) -> bytes:
    """data: build_match_card_data()가 만든 dict. logos: {'team1','team2','event': PIL.Image|None}"""
    logos = logos or {}
    stats = data.get("stats") or {}
    gid = data.get("selected")
    sides = stats.get(gid) if gid in stats else None

    n1 = len(sides[0]) if sides else 0
    n2 = len(sides[1]) if sides else 0
    table_h = lambda n: TEAM_HEAD_H + COL_HEAD_H + max(n, 1) * ROW_H + 24  # noqa: E731
    maps_h = MAPS_H if data.get("maps") else 0
    body_h = (table_h(n1) + table_h(n2)) if sides else 120
    H = HEADER_H + maps_h + 10 + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _draw_header(img, d, data, logos)
    _draw_maps(d, data, HEADER_H)

    y = HEADER_H + maps_h + 10
    if sides:
        selected_map = next((m for m in data.get("maps", []) if m["game_id"] == gid), None)
        s1 = s2 = None
        if selected_map and selected_map["status"] != "upcoming":
            s1, s2 = selected_map.get("team1_score"), selected_map.get("team2_score")
        all_players = sides[0] + sides[1]
        mvp = max(all_players, key=lambda p: _num(p.get("acs")), default=None)
        mvp_name = mvp.get("name") if mvp and _num(mvp.get("acs")) > 0 else None

        title = "전체 맵" if gid == "all" else (selected_map["name"] if selected_map else "")
        y += 14
        y = _draw_team_table(d, data["team1"], sides[0], y, str(s1) if s1 is not None else None, mvp_name, title) + 24
        y = _draw_team_table(d, data["team2"], sides[1], y, str(s2) if s2 is not None else None, mvp_name, title) + 24
    else:
        msg = "경기가 시작되면 맵별 기록이 표시됩니다." if data["status"] == "upcoming" else "기록이 아직 없습니다."
        d.text((W / 2, y + 60), msg, font=font("regular", 22), fill=MUTED, anchor="mm")
        y += body_h

    # 바닥글
    fy = H - FOOTER_H
    d.line([PAD, fy, W - PAD, fy], fill=LINE, width=1)
    d.text((PAD, fy + FOOTER_H / 2), "출처: VLR.gg", font=font("regular", 16), fill=MUTED, anchor="lm")
    if data.get("updated"):
        d.text((W - PAD, fy + FOOTER_H / 2), f"{data['updated']} 기준", font=font("regular", 16), fill=MUTED, anchor="rm")
    return to_png(img)
