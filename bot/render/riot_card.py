"""유저 전적 카드: 티어·RR·최고 티어 + 최근 경쟁전 경기 (요원, 맵, K/D/A)."""

from __future__ import annotations

from PIL import Image, ImageDraw

from bot.render.base import BG, GOLD, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT, fit_text, font, paste_logo, to_png
from bot.services.riot_stats import UserStats, tier_ko

W = 880
ROW_H, GAP = 84, 8

# 티어 번호 → 색 (아이언부터 래디언트)
_TIER_RGB = ((150, 150, 150), (172, 120, 70), (190, 196, 200), (236, 192, 70), (80, 190, 200),
             (200, 130, 220), (60, 190, 120), (240, 80, 100), (255, 240, 170))


def tier_rgb(tier_id: int | None) -> tuple[int, int, int]:
    if tier_id is None or tier_id < 3:
        return MUTED
    return _TIER_RGB[min((tier_id - 3) // 3 + 1, len(_TIER_RGB) - 1)]


def render_user_card(stats: UserStats, tier_img: Image.Image | None, agent_imgs: dict[str, Image.Image | None]) -> bytes:
    n = len(stats.matches)
    h = 300 + max(1, n) * (ROW_H + GAP) + 20
    img = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(img)

    # 머리: 티어 아이콘 + 이름 + 티어/RR/최고 티어
    d.rounded_rectangle([20, 20, W - 20, 200], radius=18, fill=PANEL)
    paste_logo(img, tier_img, (105, 110), 120, fallback_text=tier_ko(stats.tier_id))
    d = ImageDraw.Draw(img)
    title = f"{stats.name} #{stats.tag}"
    t, f = fit_text(d, title, "heavy", 40, W - 220 - 40)
    d.text((190, 62), t, font=f, fill=TEXT, anchor="lm")
    color = tier_rgb(stats.tier_id)
    line = tier_ko(stats.tier_id)
    if stats.rr is not None and (stats.tier_id or 0) >= 3:
        line += f" · {stats.rr}RR"
        if stats.last_change:
            line += f" ({stats.last_change:+d})"
    d.text((190, 112), line, font=font("bold", 30), fill=color, anchor="lm")
    sub = []
    if stats.peak_id:
        sub.append(f"최고 {tier_ko(stats.peak_id)}" + (f" ({stats.peak_season})" if stats.peak_season else ""))
    if stats.level:
        sub.append(f"레벨 {stats.level}")
    sub.append(stats.region.upper())
    d.text((190, 158), "  ·  ".join(sub), font=font("regular", 22), fill=MUTED, anchor="lm")

    # 요약
    d.rounded_rectangle([20, 212, W - 20, 272], radius=14, fill=PANEL_2)
    if n:
        parts = [(f"최근 {n}경기", MUTED), (f"{stats.wins}승 {stats.losses}패", GREEN if stats.wins >= stats.losses else RED),
                 (f"K/D {stats.avg_kd:.2f}", TEXT), (f"HS {stats.avg_hs:.0f}%", TEXT), (f"ADR {stats.avg_adr:.0f}", TEXT)]
        x = 44
        for text, col in parts:
            d.text((x, 242), text, font=font("bold", 24), fill=col, anchor="lm")
            x += d.textlength(text, font=font("bold", 24)) + 34
    else:
        d.text((44, 242), "최근 경쟁전 기록이 없어요", font=font("bold", 24), fill=MUTED, anchor="lm")

    # 경기 줄
    y = 292
    for m in stats.matches:
        bar = GREEN if m.won else RED if m.won is False else MUTED
        d.rounded_rectangle([20, y, W - 20, y + ROW_H], radius=14, fill=PANEL)
        d.rounded_rectangle([20, y, 30, y + ROW_H], radius=5, fill=bar)
        icon = agent_imgs.get(m.agent_id)
        if icon is not None:
            ic = icon.convert("RGBA").resize((60, 60), Image.LANCZOS)
            img.paste(ic, (46, y + 12), ic)
        else:
            d.ellipse([46, y + 12, 106, y + 72], fill=PANEL_2, outline=LINE, width=2)
        t, f = fit_text(d, m.map_name, "bold", 26, 190)
        d.text((124, y + 30), t, font=f, fill=TEXT, anchor="lm")
        when = m.started.strftime("%m/%d %H:%M") if m.started else ""
        d.text((124, y + 60), f"{m.agent} · {when}", font=font("regular", 18), fill=MUTED, anchor="lm")
        res = "승리" if m.won else "패배" if m.won is False else "-"
        d.text((345, y + 28), res, font=font("heavy", 26), fill=bar, anchor="lm")
        d.text((345, y + 60), f"{m.rounds_won} : {m.rounds_lost}", font=font("bold", 20), fill=MUTED, anchor="lm")
        d.text((480, y + 28), f"{m.kills} / {m.deaths} / {m.assists}", font=font("heavy", 28), fill=TEXT, anchor="lm")
        d.text((480, y + 60), f"K/D {m.kd:.2f}", font=font("regular", 18), fill=GOLD if m.kd >= 1.2 else MUTED, anchor="lm")
        d.text((700, y + 28), f"HS {m.hs_pct:.0f}%", font=font("bold", 22), fill=TEXT, anchor="lm")
        d.text((700, y + 60), f"ADR {m.adr:.0f}", font=font("regular", 18), fill=MUTED, anchor="lm")
        y += ROW_H + GAP
    d.text((W - 24, h - 14), "데이터: HenrikDev 비공식 API", font=font("regular", 14), fill=MUTED, anchor="rm")
    return to_png(img)
