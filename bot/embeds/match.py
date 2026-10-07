"""경기 표시 (목록 한 줄, 경기 상세)."""

from __future__ import annotations

import unicodedata
from typing import Any

import discord

from bot.database.models import Match
from bot.embeds.common import COLOR_MAIN, COLOR_OK, clip, ts
from bot.utils.korean import stage_ko

COLOR_LIVE = discord.Color.from_rgb(237, 66, 69)
NUM_EMOJI = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]


# ---------------------------------------------------------------------------
# 한 줄 표시
# ---------------------------------------------------------------------------


def _perspective(match: Match, team_id: int) -> tuple[str, str, int | None, int | None]:
    """(내 팀, 상대, 내 점수, 상대 점수)"""
    if match.team2_id == team_id:
        return match.team2_name, match.team1_name, match.team2_score, match.team1_score
    return match.team1_name, match.team2_name, match.team1_score, match.team2_score


def result_icon(my: int | None, opp: int | None) -> str:
    if my is None or opp is None:
        return "⚪"
    return "🟢" if my > opp else "🔴" if my < opp else "⚪"


def recent_line(match: Match, team_id: int) -> str:
    """팀 화면 최근 전적 한 줄. 예) 🟢 **2:0** FUT Esports"""
    _, opp, my, op = _perspective(match, team_id)
    score = f"{my}:{op}" if my is not None and op is not None else "-:-"
    return f"{result_icon(my, op)} **{score}** {opp}"


def short_label(match: Match, team_id: int | None = None) -> str:
    """선택 메뉴용 짧은 이름 (최대 100자)."""
    if team_id is not None:
        me, opp, my, op = _perspective(match, team_id)
    else:
        me, opp, my, op = match.team1_name, match.team2_name, match.team1_score, match.team2_score
    if match.status == "live":
        prefix = "🔴"
        score = f"{my or 0}:{op or 0}"
    elif match.status == "completed":
        prefix = result_icon(my, op) if team_id is not None else "✅"
        score = f"{my}:{op}"
    else:
        prefix, score = "📅", "vs"
    return f"{prefix} {me} {score} {opp}"[:100]


def match_line(match: Match) -> str:
    """/경기 목록의 경기 블록."""
    if match.status == "live":
        head = "🔴 **LIVE**"
        score = f"`{match.team1_score or 0} : {match.team2_score or 0}`"
    elif match.status == "completed":
        head = f"✅ {ts(match.scheduled_at, 'd')}"
        score = f"`{match.team1_score} : {match.team2_score}`"
    else:
        head = f"🕐 {ts(match.scheduled_at, 't')} · {ts(match.scheduled_at, 'R')}"
        score = "vs"
    stage = stage_ko(match.stage)
    event = (match.tournament_name or "") + (f" · {stage}" if stage else "")
    return f"{head}\n**{match.team1_name}** {score} **{match.team2_name}**" + (f"\n🏆 {event}" if event else "")


def matches_embed(title: str, matches: list[Match]) -> discord.Embed:
    embed = discord.Embed(title=title, color=COLOR_MAIN)
    if not matches:
        embed.description = "표시할 경기가 없습니다."
        return embed
    embed.description = clip("\n\n".join(match_line(m) for m in matches), 4000)
    embed.set_footer(text="아래 메뉴에서 경기를 고르면 맵별 기록을 볼 수 있어요 · VLR.gg")
    return embed


# ---------------------------------------------------------------------------
# 경기 상세
# ---------------------------------------------------------------------------


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    gap = " " * max(0, width - _width(text))
    return gap + text if right else text + gap


def _fit(text: str, width: int) -> str:
    while _width(text) > width:
        text = text[:-1]
    return text


def _num(value: Any) -> float:
    try:
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return -1.0


def stats_table(players: list[dict[str, Any]]) -> str:
    """선수 스탯 표 (코드 블록이라 정렬이 유지된다). ACS 높은 순."""
    if not players:
        return "기록 없음"
    rows = sorted(players, key=lambda p: _num(p.get("acs")), reverse=True)
    lines = [f"{_pad('선수', 10)} {_pad('K/D/A', 8)} {_pad('ACS', 3, True)} {_pad('ADR', 3, True)} {_pad('HS', 4, True)}"]
    for p in rows:
        if p.get("kills") is None and p.get("deaths") is None:
            kda = "-"
        else:
            kda = f"{p.get('kills') or 0}/{p.get('deaths') or 0}/{p.get('assists') or 0}"
        lines.append(
            f"{_pad(_fit(p.get('name') or '?', 10), 10)} {_pad(kda, 8)} "
            f"{_pad(p.get('acs') or '-', 3, True)} {_pad(p.get('adr') or '-', 3, True)} {_pad(p.get('hs') or '-', 4, True)}"
        )
    return "```\n" + "\n".join(lines) + "\n```"


def map_lines(detail: dict[str, Any], team1: str, team2: str) -> str:
    lines = []
    for m in detail.get("maps", []):
        num = NUM_EMOJI[m["order"]] if 0 <= m["order"] < len(NUM_EMOJI) else f"{m['order']}."
        s1, s2 = m.get("team1_score"), m.get("team2_score")
        if m["status"] == "upcoming":
            lines.append(f"{num} {m['name']} — 미진행")
            continue
        score = f"`{s1 if s1 is not None else 0} : {s2 if s2 is not None else 0}`"
        if m["status"] == "live":
            tail = "🔴 진행 중"
        elif s1 is not None and s2 is not None and s1 != s2:
            tail = f"🏆 {team1 if s1 > s2 else team2}"
        else:
            tail = ""
        pick = {1: team1, 2: team2}.get(m.get("picked_by"))
        pick_text = f" · {pick} 픽" if pick else (" · 디사이더" if m["order"] > 1 else "")
        lines.append(f"{num} **{m['name']}** {score} {tail}{pick_text}")
    return "\n".join(lines) or "맵 정보 없음"


def default_game_id(detail: dict[str, Any]) -> str:
    """처음 보여줄 맵: 진행 중인 맵 → 전체."""
    live = next((m["game_id"] for m in detail.get("maps", []) if m["status"] == "live"), None)
    return live or "all"


def match_detail_embed(match: Match, game_id: str | None = None, *, stale: bool = False) -> discord.Embed:
    detail: dict[str, Any] = match.detail or {}
    status = detail.get("status", match.status)
    t1 = (detail.get("team1") or {}).get("name") or match.team1_name
    t2 = (detail.get("team2") or {}).get("name") or match.team2_name
    s1 = detail.get("team1_score", match.team1_score)
    s2 = detail.get("team2_score", match.team2_score)

    if status == "live":
        color, head = COLOR_LIVE, "🔴 **LIVE**"
    elif status == "completed":
        color, head = COLOR_OK, "✅ 경기 종료"
    else:
        color, head = COLOR_MAIN, f"🕐 {ts(match.scheduled_at, 'f')} 시작"

    score = f"{s1} : {s2}" if s1 is not None and s2 is not None and status != "upcoming" else "vs"
    embed = discord.Embed(title=f"{t1}  {score}  {t2}", url=match.vlr_url, color=color)

    event = detail.get("event") or {}
    stage = stage_ko(event.get("stage") or match.stage)
    sub = " · ".join(x for x in (event.get("name") or match.tournament_name, stage, detail.get("best_of")) if x)
    embed.description = f"{head}" + (f"\n🏆 {sub}" if sub else "") + (
        f"\n📅 {ts(match.scheduled_at, 'f')}" if status != "upcoming" and match.scheduled_at else ""
    )
    if event.get("logo"):
        embed.set_thumbnail(url=event["logo"])

    if detail.get("maps"):
        embed.add_field(name="🗺️ 맵", value=clip(map_lines(detail, t1, t2)), inline=False)

    stats = detail.get("stats") or {}
    gid = game_id or default_game_id(detail)
    if gid not in stats:
        gid = "all" if "all" in stats else next(iter(stats), None)
    if gid is not None:
        map_name = "전체 맵" if gid == "all" else next(
            (m["name"] for m in detail.get("maps", []) if m["game_id"] == gid), "맵"
        )
        side1, side2 = stats[gid][0], stats[gid][1]
        embed.add_field(name=f"{t1} · {map_name}", value=clip(stats_table(side1)), inline=False)
        embed.add_field(name=f"{t2} · {map_name}", value=clip(stats_table(side2)), inline=False)
    elif status == "upcoming":
        embed.add_field(name="📊 기록", value="경기가 시작되면 맵별 기록이 표시됩니다.", inline=False)

    footer = "VLR.gg · 기록 갱신"
    if stale:
        footer = "⚠️ 최신 정보를 가져오지 못해 이전 기록을 표시합니다 · " + footer
    embed.set_footer(text=footer)
    if match.detail_scraped_at:
        embed.timestamp = match.detail_scraped_at
    return embed
