"""/도움말 — 봇에 실제로 등록된 명령어 목록에서 자동으로 만든다 (명령어를 추가해도 따로 고칠 필요 없음)."""

from __future__ import annotations

from typing import Any, Iterable

import discord

from bot.embeds.common import COLOR_MAIN, clip

CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("📅 경기·팀", ("팀", "팀맵", "경기", "전적", "일정", "대진표")),
    ("📊 랭킹·비교", ("랭킹", "비교")),
    ("🎯 선수", ("선수", "선수비교")),
    ("🎨 스킨", ("스킨", "스킨목록", "세트", "세트목록")),
    ("💰 VP·예측 게임", ("vp", "출석", "출첵", "vp랭킹", "예측", "내예측", "예측현황")),
    ("🎰 미니게임", ("동전", "주사위", "슬롯", "블랙잭", "퀴즈", "지뢰찾기")),
    ("📈 주식", ("주식", "주식시간", "매수", "매도", "내주식", "거래내역", "주식순위", "주식추이")),
    ("🛍️ 프로필·꾸미기", ("프로필", "프로필상점", "꾸미기", "프로필설정")),
    ("🔧 기타", ("도움말", "ping")),
]
ADMIN_GROUP = "관리"


def flatten(commands: Iterable[Any], prefix: str = "") -> list[tuple[str, str, list[tuple[str, bool]]]]:
    """(전체 이름, 설명, [(인자 이름, 필수 여부)]) 목록. 그룹은 펼친다 (예: '관리 팀갱신')."""
    out = []
    for c in commands:
        name = f"{prefix}{c.name}"
        children = getattr(c, "commands", None)
        if children is not None:           # 그룹
            out.extend(flatten(children, prefix=name + " "))
        else:
            params = [(p.name, bool(p.required)) for p in getattr(c, "parameters", [])]
            out.append((name, c.description, params))
    return out


def usage(name: str, params: list[tuple[str, bool]]) -> str:
    parts = [f"/{name}"] + [f"<{n}>" if req else f"[{n}]" for n, req in params]
    return " ".join(parts)


def help_sections(commands: Iterable[Any], *, show_admin: bool) -> list[tuple[str, str]]:
    """(제목, 본문) 목록. discord에 의존하지 않아 테스트하기 쉽다."""
    entries = flatten(commands)
    by_root: dict[str, list[tuple[str, str, list[tuple[str, bool]]]]] = {}
    for e in entries:
        by_root.setdefault(e[0].split(" ")[0], []).append(e)

    sections: list[tuple[str, str]] = []
    used: set[str] = set()
    for title, roots in CATEGORIES:
        lines = []
        for root in roots:
            for name, desc, params in by_root.get(root, []):
                lines.append(f"`{usage(name, params)}`\n└ {desc}")
            used.add(root)
        if lines:
            sections.append((title, "\n".join(lines)))

    # 분류에 없는 새 명령어는 따로 모아 보여준다 (관리 그룹 제외)
    extra = [e for root, es in by_root.items() if root not in used and root != ADMIN_GROUP for e in es]
    if extra:
        sections.append(("✨ 그 밖의 명령어", "\n".join(f"`{usage(n, p)}`\n└ {d}" for n, d, p in extra)))

    if show_admin and by_root.get(ADMIN_GROUP):
        sections.append(("🔒 관리자 전용", "\n".join(f"`{usage(n, p)}` — {d}" for n, d, p in by_root[ADMIN_GROUP])))
    return sections


def build_help(commands: Iterable[Any], *, show_admin: bool) -> discord.Embed:
    embed = discord.Embed(
        title="📖 도움말",
        description="VALORANT 프로 팀·선수·경기 정보를 보여주는 봇이에요.\n"
                    "`<>`는 필수, `[]`는 선택 입력이에요. 팀·선수 이름은 입력하면 **자동완성**이 떠요.",
        color=COLOR_MAIN,
    )
    for title, body in help_sections(commands, show_admin=show_admin):
        embed.add_field(name=title, value=clip(body), inline=False)
    embed.set_footer(text="데이터 출처: VLR.gg · Riot Games와 무관한 비공식 팬 프로젝트입니다")
    return embed
