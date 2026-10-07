"""DB 데이터 → 카드 데이터 → PNG.

이미지에는 시각이 그림으로 박히므로 한국 시간(KST)으로 표시한다. (DISPLAY_TZ 환경변수로 변경 가능)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from bot.database.models import Match
from bot.database.repository import TeamDetail
from bot.render import images
from bot.render.base import render_enabled
from bot.render.bracket_card import render_bracket_card
from bot.render.compare_card import render_compare_card
from bot.render.match_card import render_match_card
from bot.render.player_card import render_player_card
from bot.render.player_stats_card import player_stats_data, render_player_stats_card
from bot.render.ranking_card import render_ranking_card
from bot.render.team_card import render_team_card
from bot.utils.korean import STAFF_ROLES, country_ko, role_ko, stage_ko

log = logging.getLogger("valobot.render.cards")

DISPLAY_TZ = ZoneInfo(os.getenv("DISPLAY_TZ", "Asia/Seoul"))
_WEEKDAY = "월화수목금토일"


async def _render(fn: Any, *args: Any) -> bytes:
    """카드 그리기(별도 스레드) + 걸린 시간 로그. 느린 곳을 찾을 때 /관리 로그에서 '[성능]'을 검색."""
    t0 = time.perf_counter()
    png = await asyncio.to_thread(fn, *args)
    log.info("[성능] %s 렌더 %dms (%dKB)", fn.__name__, (time.perf_counter() - t0) * 1000, len(png) // 1024)
    return png


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
        return await _render(render_team_card, data, {"team": fetched.get("team")})
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
        return await _render(render_match_card, data, logos)
    except Exception:
        log.exception("경기 카드 생성 실패 (match %s)", match.vlr_id)
        return None


# ---------------------------------------------------------------------------
# 선수 카드
# ---------------------------------------------------------------------------

GEAR_ORDER = [("mouse", "마우스"), ("keyboard", "키보드"), ("mousepad", "마우스패드"),
              ("monitor", "모니터"), ("headset", "헤드셋")]


def _fmt_num(v: float | int | None, digits: int = 3) -> str | None:
    if v is None:
        return None
    if isinstance(v, float):
        text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(v)


def _line_text(part: dict[str, Any], prefix: str) -> str:
    show = str(part.get(f"show_{prefix}_lines", "")).lower()
    if not show:
        return "-"
    if show != "on":
        return "끔"
    get = lambda k: part.get(f"{prefix}_line_{k}", "-")  # noqa: E731
    return f"길이 {get('length')} · 두께 {get('thickness')} · 간격 {get('offset')} · 투명도 {get('opacity')}"


def _onoff(v: str | None) -> str:
    if not v:
        return "-"
    low = v.lower()
    return "켬" if low == "on" else "끔" if low == "off" else v


async def build_player_card(detail: Any, empty_message: str | None = None) -> bytes | None:
    """선수 카드 PNG (detail: repository.PlayerDetail). 실패하면 None."""
    if not render_enabled():
        return None
    p, s, ch = detail.player, detail.settings, detail.crosshair
    try:
        tiles: list[tuple[str, str, bool]] = []
        if s is not None:
            for label, value, hl in (
                ("DPI", _fmt_num(s.dpi), False),
                ("감도", _fmt_num(s.sensitivity), False),
                ("eDPI", _fmt_num(s.edpi, 1), True),
                ("스코프 감도", _fmt_num(s.scoped_sensitivity), False),
                ("폴링레이트", f"{s.polling_rate} Hz" if s.polling_rate else None, False),
                ("윈도우 감도", _fmt_num(s.windows_sensitivity), False),
            ):
                tiles.append((label, value or "-", hl))
        video = None
        if s is not None and s.resolution:
            video = " · ".join(x for x in (f"해상도 {s.resolution}", s.aspect_ratio, s.scaling_mode) if x)

        by_cat = {e.category: e.name for e in detail.equipment}
        gear = [(label, by_cat[key]) for key, label in GEAR_ORDER if key in by_cat]

        ch_rows: list[tuple[str, str]] = []
        raw: dict[str, Any] = {}
        manual = bool(s is not None and (s.raw or {}).get("manual"))
        if ch is not None and not (ch.raw or {}).get("manual"):
            raw = ch.raw or {}
            ch_rows = [
                ("색상", ch.color or "-"),
                ("외곽선", _onoff(ch.outlines)),
                ("중앙 점", _onoff(ch.center_dot)),
                ("내부 선", _line_text(raw.get("inner") or {}, "inner")),
                ("외부 선", _line_text(raw.get("outer") or {}, "outer")),
            ]

        team = detail.team
        fetched = await images.fetch_many({"photo": p.photo_url, "team": team.logo_url if team else None})
        team_name = team.name if team else ((s.raw or {}).get("team") if s is not None and s.raw else None)
        updated = None
        if s is not None and s.source_updated_at:
            u = s.source_updated_at.astimezone(DISPLAY_TZ)
            updated = f"{u.year}년 {u.month}월 {u.day}일"
        data = {
            "name": p.nickname,
            "real_name": p.real_name,
            "team": team_name,
            "country": country_ko(p.country_code, p.country_name),
            "tiles": tiles,
            "video": video,
            "gear": gear,
            "crosshair_rows": ch_rows,
            "crosshair_raw": raw,
            "crosshair_code": ch.code if ch is not None else None,
            "manual": manual,
            "updated": updated,
            "empty_message": empty_message or "ProSettings에 등록된 설정이 없는 선수입니다.",
        }
        return await _render(render_player_card, data, fetched)
    except Exception:
        log.exception("선수 카드 생성 실패 (%s)", p.nickname)
        return None


async def build_ranking_card(title: str, subtitle: str, ranked: list[tuple[int, Any]], footer: str) -> bytes | None:
    """랭킹 카드 PNG (ranked: [(표시 순위, RankingEntry)]). 실패하면 None."""
    if not render_enabled():
        return None
    try:
        fetched = await images.fetch_many({f"t{i}": e.logo_url for i, (_, e) in enumerate(ranked)})
        rows = [
            {"rank": rank, "name": e.name, "rating": e.rating, "streak": e.streak,
             "country": e.country, "logo_key": f"t{i}"}
            for i, (rank, e) in enumerate(ranked)
        ]
        data = {"title": title, "subtitle": subtitle, "rows": rows, "footer": footer}
        return await _render(render_ranking_card, data, fetched)
    except Exception:
        log.exception("랭킹 카드 생성 실패")
        return None


async def build_compare_card(result: Any) -> bytes | None:
    """두 팀 비교 카드 PNG (result: compare_service.CompareResult). 실패하면 None."""
    if not render_enabled():
        return None
    try:
        a, b = result.a, result.b

        def side(detail: TeamDetail) -> dict[str, Any]:
            t = detail.team
            form = []
            for m in detail.recent:
                _, my, op = _perspective(m, t.id)
                if my is not None and op is not None and my != op:
                    form.append("W" if my > op else "L")
            roster = [m.name for m in detail.members if m.role not in STAFF_ROLES and m.role != "inactive"][:6]
            return {"name": t.name, "country": country_ko(t.country_code, t.country_name) or "-",
                    "form": form, "roster": roster}

        a_wins = b_wins = 0
        h2h_rows = []
        for m in result.h2h:
            _, my, op = _perspective(m, a.team.id)  # a 팀 기준
            if my is None or op is None:
                continue
            winner = "a" if my > op else "b" if my < op else None
            a_wins += winner == "a"
            b_wins += winner == "b"
            h2h_rows.append({"date": fmt_dt(m.scheduled_at, with_time=False), "score_a": my, "score_b": op,
                             "winner": winner, "event": m.tournament_name})
        logos = await images.fetch_many({"a": a.team.logo_url, "b": b.team.logo_url})
        data = {
            "a": side(a), "b": side(b),
            "h2h": {"a_wins": a_wins, "b_wins": b_wins, "rows": h2h_rows},
            "footer": "저장된 경기 기준 · 출처: VLR.gg",
        }
        return await _render(render_compare_card, data, logos)
    except Exception:
        log.exception("팀 비교 카드 생성 실패")
        return None


async def build_bracket_card(bracket: Any, stale: bool = False) -> bytes | None:
    """대회 대진표 카드 PNG (bracket: vlr.EventBracket). 실패하면 None."""
    if not render_enabled():
        return None
    try:
        urls: dict[str, str | None] = {"event": bracket.logo_url}
        sections = []
        for si, sec in enumerate(bracket.sections):
            cols = []
            for ci, col in enumerate(sec.columns):
                matches = []
                for mi, m in enumerate(col.matches):
                    row = {}
                    for key, t in (("t1", m.team1), ("t2", m.team2)):
                        lk = f"s{si}c{ci}m{mi}{key}"
                        urls[lk] = t.logo_url
                        row[key] = {"name": t.name, "score": t.score, "winner": t.winner, "loser": t.loser, "logo_key": lk}
                    finished = m.team1.winner or m.team2.winner
                    row["when"] = "" if finished else fmt_dt(m.scheduled_at)
                    row["live"] = m.live
                    matches.append(row)
                cols.append({"label": stage_ko(col.label) or col.label, "matches": matches})
            sections.append({"kind": sec.kind, "columns": cols})
        logos = await images.fetch_many(urls)
        footer = "시간은 한국 시간 기준 · 출처: VLR.gg" + (" · 최신 정보를 못 가져와 이전 결과입니다" if stale else "")
        data = {"title": bracket.name, "subtitle": "대진표 · VLR.gg", "sections": sections, "footer": footer}
        return await _render(render_bracket_card, data, logos)
    except Exception:
        log.exception("대진표 카드 생성 실패 (%s)", getattr(bracket, "name", "?"))
        return None


async def build_player_stats_card(page: Any) -> bytes | None:
    """선수 통계 카드 PNG. 실패하면 None."""
    if not render_enabled():
        return None
    try:
        urls = {"photo": page.photo_url, "team_logo": page.team_logo_url}
        for i, a in enumerate(page.agents):
            urls[f"agent{i}"] = f"https://www.vlr.gg/img/vlr/game/agents/{a.agent.lower()}.png"
        fetched = await images.fetch_many(urls)
        return await _render(render_player_stats_card, player_stats_data(page), fetched)
    except Exception:
        log.exception("선수 통계 카드 생성 실패")
        return None
