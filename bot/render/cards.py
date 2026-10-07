"""DB 데이터 → 카드 데이터 → PNG.

이미지에는 시각이 그림으로 박히므로 한국 시간(KST)으로 표시한다. (DISPLAY_TZ 환경변수로 변경 가능)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from bot.database.models import Match
from bot.database.repository import TeamDetail
from bot.render import images
from bot.render.base import render_enabled
from bot.render.match_card import render_match_card
from bot.render.team_card import render_team_card
from bot.utils.korean import STAFF_ROLES, country_ko, role_ko, stage_ko

log = logging.getLogger("valobot.render.cards")

DISPLAY_TZ = ZoneInfo(os.getenv("DISPLAY_TZ", "Asia/Seoul"))
_WEEKDAY = "월화수목금토일"


def fmt_dt(dt: datetime | None, *, with_time: bool = True) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(DISPLAY_TZ)
    date = f"{local.month}월 {local.day}일 ({_WEEKDAY[local.weekday()]})"
    if not with_time:
        return f"{local.month}월 {local.day}일"
    ampm = "오전" if local.hour < 12 else "오후"
    hour = local.hour % 12 or 12
    return f"{date} {ampm} {hour}:{local.minute:02d}"


def fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(DISPLAY_TZ)
    ampm = "오전" if local.hour < 12 else "오후"
    return f"{ampm} {local.hour % 12 or 12}:{local.minute:02d}"


def _perspective(match: Match, team_id: int) -> tuple[str, int | None, int | None]:
    if match.team2_id == team_id:
        return match.team1_name, match.team2_score, match.team1_score
    return match.team2_name, match.team1_score, match.team2_score


# ---------------------------------------------------------------------------
# 팀 카드
# ---------------------------------------------------------------------------


async def build_team_card(detail: TeamDetail) -> bytes | None:
    """팀 카드 PNG. 폰트가 없거나 실패하면 None (→ 텍스트 Embed로 대체)."""
    if not render_enabled():
        return None
    team = detail.team
    try:
        players, staff = [], []
        photo_urls: dict[str, str | None] = {"team": team.logo_url}
        for i, m in enumerate(detail.members):
            if m.role in STAFF_ROLES:
                staff.append({"name": m.name, "role": role_ko(m.role)})
                continue
            key = f"p{i}"
            photo_urls[key] = m.photo_url
            players.append({
                "key": key,
                "name": m.name,
                "real_name": m.real_name,
                "captain": m.is_captain,
                "role": role_ko(m.role) if m.role != "player" else None,
            })

        recent = []
        for m in detail.recent:
            opp, my, op = _perspective(m, team.id)
            result = "W" if my is not None and op is not None and my > op else (
                "L" if my is not None and op is not None and my < op else "-")
            recent.append({
                "result": result,
                "score": f"{my} : {op}" if my is not None and op is not None else "- : -",
                "opponent": opp,
                "event": m.tournament_name,
                "date": fmt_dt(m.scheduled_at, with_time=False),
            })

        banner = None
        live = next((m for m in detail.upcoming if m.status == "live"), None)
        nxt = next((m for m in detail.upcoming if m.status == "upcoming"), None)
        if live:
            opp, my, op = _perspective(live, team.id)
            banner = {"kind": "live", "opponent": opp, "right": f"{my or 0} : {op or 0}"}
        elif nxt:
            opp, _, _ = _perspective(nxt, team.id)
            banner = {"kind": "next", "opponent": opp, "right": fmt_dt(nxt.scheduled_at) or "시간 미정"}

        event = next((m.tournament_name for m in detail.upcoming + detail.recent if m.tournament_name), None)
        fetched = await images.fetch_many(photo_urls)
        for p in players:
            p["photo"] = fetched.get(p.pop("key"))

        data = {
            "name": team.name,
            "tag": team.tag,
            "country": country_ko(team.country_code, team.country_name) or "",
            "event": event,
            "banner": banner,
            "players": players,
            "staff": staff,
            "recent": recent,
            "updated": fmt_dt(team.last_scraped_at),
        }
        return await asyncio.to_thread(render_team_card, data, {"team": fetched.get("team")})
    except Exception:
        log.exception("팀 카드 생성 실패 (%s)", team.name)
        return None


# ---------------------------------------------------------------------------
# 경기 카드
# ---------------------------------------------------------------------------


async def build_match_card(match: Match, game_id: str) -> bytes | None:
    if not render_enabled():
        return None
    try:
        detail: dict[str, Any] = match.detail or {}
        t1 = detail.get("team1") or {}
        t2 = detail.get("team2") or {}
        event = detail.get("event") or {}
        status = detail.get("status", match.status)

        logos = await images.fetch_many({
            "team1": t1.get("logo"),
            "team2": t2.get("logo"),
            "event": event.get("logo"),
        })
        data = {
            "team1": t1.get("name") or match.team1_name,
            "team2": t2.get("name") or match.team2_name,
            "score1": detail.get("team1_score", match.team1_score),
            "score2": detail.get("team2_score", match.team2_score),
            "status": status,
            "event": event.get("name") or match.tournament_name or "",
            "stage": stage_ko(event.get("stage") or match.stage),
            "best_of": detail.get("best_of"),
            "when": fmt_dt(match.scheduled_at),
            "maps": detail.get("maps") or [],
            "stats": detail.get("stats") or {},
            "selected": game_id,
            "updated": fmt_time(match.detail_scraped_at),
        }
        return await asyncio.to_thread(render_match_card, data, logos)
    except Exception:
        log.exception("경기 카드 생성 실패 (match %s)", match.vlr_id)
        return None
