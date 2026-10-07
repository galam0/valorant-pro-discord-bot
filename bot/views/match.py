"""경기 상세 화면의 버튼·선택 메뉴."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import discord

from bot.database.models import Match
from bot.embeds.common import error_embed
from bot.embeds.match import default_game_id, match_detail_embed, short_label
from bot.render.cards import build_match_card
from bot.scrapers.http import ScrapeError
from bot.services import match_service

log = logging.getLogger("valobot.views.match")

VIEW_TIMEOUT = 30 * 60  # 30분 동안 버튼·메뉴 사용 가능

# (vlr_id, 메뉴에 보일 이름)
MatchChoice = tuple[int, str]


def choices_from(matches: list[Match], team_id: int | None = None) -> list[MatchChoice]:
    return [(m.vlr_id, short_label(m, team_id)) for m in matches][:25]


async def build_match_message(
    vlr_id: int,
    *,
    game_id: str | None = None,
    others: list[MatchChoice] | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], discord.ui.View]:
    """경기 상세 메시지 내용. 이미지 카드가 되면 {'file': ...}, 아니면 {'embed': ...}."""
    result = await match_service.get_match_detail(vlr_id, force=force)
    detail = result.match.detail or {}
    gid = game_id or default_game_id(detail)
    view = MatchDetailView(result.match, gid, others or [])

    png = await build_match_card(result.match, gid)
    if png is not None:
        payload: dict[str, Any] = {"file": discord.File(BytesIO(png), filename=f"match_{vlr_id}.png")}
        if result.stale:
            payload["content"] = "⚠️ 최신 정보를 가져오지 못해 이전 기록을 표시합니다."
        return payload, view
    return {"embed": match_detail_embed(result.match, gid, stale=result.stale)}, view


def edit_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """메시지 수정용: 이미지 ↔ Embed 전환까지 처리."""
    if "file" in payload:
        return {"attachments": [payload["file"]], "embed": None, "content": payload.get("content")}
    return {"embed": payload["embed"], "attachments": [], "content": None}


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ScrapeError):
        return "VLR.gg에서 경기 기록을 가져오지 못했습니다. 잠시 후 다시 시도해주세요."
    return "경기 기록을 불러오는 중 오류가 발생했습니다."


async def send_match_detail(
    interaction: discord.Interaction, vlr_id: int, *, others: list[MatchChoice] | None = None
) -> None:
    """새 메시지로 경기 상세를 보낸다 (명령어·다른 화면의 메뉴에서 호출)."""
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)
    try:
        payload, view = await build_match_message(vlr_id, others=others)
    except Exception as exc:
        log.warning("경기 상세 실패 (match %s): %s", vlr_id, exc)
        await interaction.followup.send(embed=error_embed(_friendly_error(exc)), ephemeral=True)
        return
    await interaction.followup.send(**payload, view=view)


async def _edit_with(interaction: discord.Interaction, vlr_id: int, **kwargs: Any) -> None:
    """같은 메시지를 다른 맵/경기로 바꿔서 다시 그린다."""
    await interaction.response.defer()
    try:
        payload, view = await build_match_message(vlr_id, **kwargs)
    except Exception as exc:
        log.warning("경기 상세 갱신 실패 (match %s): %s", vlr_id, exc)
        await interaction.followup.send(embed=error_embed(_friendly_error(exc)), ephemeral=True)
        return
    await interaction.edit_original_response(**edit_kwargs(payload), view=view)


class MapSelect(discord.ui.Select):
    def __init__(self, match: Match, selected: str, others: list[MatchChoice]) -> None:
        detail = match.detail or {}
        stats = detail.get("stats") or {}
        options = []
        if "all" in stats:
            options.append(discord.SelectOption(label="전체 맵", value="all", emoji="📊", default=selected == "all"))
        for m in detail.get("maps", []):
            if m["game_id"] not in stats:
                continue
            s1, s2 = m.get("team1_score"), m.get("team2_score")
            score = f" {s1}:{s2}" if s1 is not None and s2 is not None else ""
            options.append(
                discord.SelectOption(
                    label=f"{m['order']}세트 {m['name']}{score}"[:100],
                    value=m["game_id"],
                    emoji="🔴" if m["status"] == "live" else "🗺️",
                    default=selected == m["game_id"],
                )
            )
        super().__init__(placeholder="맵 선택", options=options[:25] or [discord.SelectOption(label="기록 없음", value="none")],
                         disabled=not options, row=0)
        self.vlr_id = match.vlr_id
        self.others = others

    async def callback(self, interaction: discord.Interaction) -> None:
        await _edit_with(interaction, self.vlr_id, game_id=self.values[0], others=self.others)


class OtherMatchSelect(discord.ui.Select):
    def __init__(self, current: int, others: list[MatchChoice]) -> None:
        options = [
            discord.SelectOption(label=label, value=str(vid), default=vid == current)
            for vid, label in others[:25]
        ]
        super().__init__(placeholder="다른 경기 보기", options=options, row=1)
        self.others = others

    async def callback(self, interaction: discord.Interaction) -> None:
        await _edit_with(interaction, int(self.values[0]), others=self.others)


class MatchDetailView(discord.ui.View):
    def __init__(self, match: Match, selected: str, others: list[MatchChoice]) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.vlr_id = match.vlr_id
        self.selected = selected
        self.others = others

        self.add_item(MapSelect(match, selected, others))
        if len(others) > 1:
            self.add_item(OtherMatchSelect(match.vlr_id, others))

        status = (match.detail or {}).get("status", match.status)
        if status != "live":
            self.remove_item(self.refresh)
        if match.vlr_url:
            self.add_item(discord.ui.Button(label="VLR.gg", url=match.vlr_url, emoji="🔗", row=2))

    @discord.ui.button(label="새로고침", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # 진행 중 경기 캐시는 1분이라, 1분 안에 다시 누르면 같은 기록이 나온다 (사이트 보호)
        await _edit_with(interaction, self.vlr_id, game_id=self.selected, others=self.others)


class MatchOpenSelect(discord.ui.Select):
    """경기 목록/팀 화면에서 경기를 골라 상세를 새 메시지로 연다."""

    def __init__(self, choices: list[MatchChoice], placeholder: str = "경기 기록 보기", row: int = 0) -> None:
        options = [discord.SelectOption(label=label, value=str(vid)) for vid, label in choices[:25]]
        super().__init__(placeholder=placeholder, options=options, row=row)
        self.choices = choices

    async def callback(self, interaction: discord.Interaction) -> None:
        await send_match_detail(interaction, int(self.values[0]), others=self.choices)


class MatchListView(discord.ui.View):
    def __init__(self, choices: list[MatchChoice]) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        if choices:
            self.add_item(MatchOpenSelect(choices))
