"""선수 정보 Embed (이미지 카드를 만들 수 없을 때 대체용)."""

from __future__ import annotations

import discord

from bot.database.repository import PlayerDetail
from bot.embeds.common import COLOR_MAIN
from bot.utils.korean import country_ko, flag_emoji

GEAR_LABEL = {"mouse": "마우스", "keyboard": "키보드", "mousepad": "마우스패드", "monitor": "모니터", "headset": "헤드셋"}


def player_embed(detail: PlayerDetail) -> discord.Embed:
    p, s, ch = detail.player, detail.settings, detail.crosshair
    desc = [x for x in (
        p.real_name,
        f"{flag_emoji(p.country_code)} {country_ko(p.country_code, p.country_name) or ''}".strip(),
        detail.team.name if detail.team else None,
    ) if x]
    embed = discord.Embed(title=p.nickname, url=p.prosettings_url or p.vlr_url,
                          description="\n".join(desc), color=COLOR_MAIN)
    if p.photo_url:
        embed.set_thumbnail(url=p.photo_url)

    if s is not None:
        lines = [
            f"DPI **{s.dpi or '-'}** · 감도 **{s.sensitivity if s.sensitivity is not None else '-'}**",
            f"eDPI **{s.edpi or '-'}** · 스코프 감도 **{s.scoped_sensitivity or '-'}**",
            f"폴링레이트 **{s.polling_rate or '-'} Hz** · 해상도 **{s.resolution or '-'}**",
        ]
        embed.add_field(name="🎯 게임 설정", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🎯 게임 설정", value="ProSettings에 등록된 설정이 없습니다.", inline=False)

    gear = [f"{GEAR_LABEL[e.category]} · {e.name}" for e in detail.equipment if e.category in GEAR_LABEL]
    if gear:
        embed.add_field(name="🖱️ 장비", value="\n".join(gear)[:1024], inline=False)
    if ch is not None:
        embed.add_field(
            name="➕ 크로스헤어",
            value=f"색상 {ch.color or '-'} · 외곽선 {ch.outlines or '-'} · 중앙 점 {ch.center_dot or '-'}\n"
                  f"내부 선 {ch.inner_lines or '-'} · 외부 선 {ch.outer_lines or '-'}"
                  + (f"\n`{ch.code}`" if ch.code else ""),
            inline=False,
        )
    embed.set_footer(text="출처: ProSettings.net · 설정 업데이트")
    if s is not None and s.source_updated_at:
        embed.timestamp = s.source_updated_at
    return embed
