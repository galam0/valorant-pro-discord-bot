"""외부 서비스 없이 돌아가는 핵심 로직 테스트.  실행: python -m unittest discover -s tests -v"""

import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from tests import _stubs  # noqa: F401  (다른 import보다 먼저)

from bot.render.base import lighten_dark_logo
from bot.render.compare_card import render_compare_card
from bot.render.player_card import render_player_card
from bot.render.ranking_card import render_ranking_card
from bot.render.bracket_card import render_bracket_card
from bot.scrapers.vlr import parse_match_odds, ParseError, parse_event_bracket, parse_player_page, parse_rankings, parse_search_events
from bot.render.schedule_card import render_schedule_card
from bot.render.player_stats_card import player_stats_data, render_player_stats_card
from bot.services.ranking_service import _tokens, is_first_team
from bot.utils.korean import flag_emoji

PNG = b"\x89PNG"

RANK_HTML = """
<div class="rank-item wf-card fc-flex"><div class="rank-item-rank"><div class="rank-item-rank-num"> 1 </div></div>
<a href="/team/11060/nongshim-redforce" class="rank-item-team fc-flex"><img src="//owcdn.net/img/a.png">
<div class="ge-text"> Nongshim RedForce <span class="ge-text-light"> #AZ6 </span>
<div class="rank-item-team-country">South Korea</div><!--9192--></div></a>
<div data-sort-value="2000" class="rank-item-rating"> 2000 <!-- x --></div>
<div data-sort-value="2" class="rank-item-streak"><span>2W</span></div></div>
<div class="rank-item wf-card fc-flex"><div class="rank-item-rank"><div class="rank-item-rank-num"> 2 </div></div>
<a href="/team/14/t1" class="rank-item-team fc-flex"><img src="//owcdn.net/img/b.png">
<div class="ge-text"> T1 <div class="rank-item-team-country">South Korea</div></div></a>
<div data-sort-value="1905" class="rank-item-rating"> 1905 </div>
<div data-sort-value="-1" class="rank-item-streak"><span>1L</span></div></div>
"""


class ParseRankingsTest(unittest.TestCase):
    def test_parses_rows(self):
        rows = parse_rankings(RANK_HTML)
        self.assertEqual([r.name for r in rows], ["Nongshim RedForce", "T1"])  # 주석/태그 숫자가 섞이지 않음
        self.assertEqual((rows[0].rank, rows[0].vlr_id, rows[0].rating, rows[0].streak), (1, 11060, 2000, 2))
        self.assertEqual(rows[1].streak, -1)
        self.assertEqual(rows[0].country, "South Korea")

    def test_structure_change_raises(self):
        with self.assertRaises(ParseError):
            parse_rankings("<html><body>nothing</body></html>")


class FirstTeamTest(unittest.TestCase):
    def test_first_team(self):
        for name in ("T1", "Gen.G", "KIWOOM DRX", "Nongshim RedForce", "Leviatán", "KRÜ Esports",
                     "Movistar KOI", "Cloud9", "Team Vitality", "FNATIC"):
            self.assertTrue(is_first_team(name), name)

    def test_not_first_team(self):
        for name in ("T1 Academy", "DRX Youth", "Gen.G Global Academy", "Cloud9 Academy",
                     "Strom Reign", "Dplus Esports", "Formula1", "SOLATI", ""):
            self.assertFalse(is_first_team(name), name)

    def test_tokens(self):
        self.assertEqual(_tokens("Leviatán"), ["leviatan"])
        self.assertEqual(_tokens("Gen.G"), ["gen", "g"])


class KoreanUtilTest(unittest.TestCase):
    def test_flag(self):
        self.assertEqual(flag_emoji("kr"), "🇰🇷")
        self.assertEqual(flag_emoji("uk"), flag_emoji("gb"))
        self.assertEqual(flag_emoji(None), "🌐")
        self.assertEqual(flag_emoji("korea"), "🌐")


class RenderSmokeTest(unittest.TestCase):
    """폰트가 있으면 카드가 PNG로 만들어지는지(예외 없이) 확인."""

    def test_ranking_card(self):
        rows = [dict(rank=i, name=f"Team {i}" * (3 if i == 4 else 1), rating=2000 - i, streak=i - 3,
                     country="South Korea", logo_key=None) for i in range(1, 8)]
        png = render_ranking_card({"title": "한국 팀 랭킹", "subtitle": "x", "rows": rows, "footer": "f"}, {})
        self.assertTrue(png.startswith(PNG))

    def test_compare_card_with_and_without_h2h(self):
        side = {"name": "T1", "country": "대한민국", "form": ["W", "L"], "roster": ["a", "b", "c", "d", "e"]}
        for rows in ([], [{"date": "10월 3일", "score_a": 2, "score_b": 1, "winner": "a", "event": "Champions"}]):
            data = {"a": side, "b": {**side, "name": "아주아주아주아주 긴 이름의 팀 이름 테스트", "form": []},
                    "h2h": {"a_wins": 1, "b_wins": 0, "rows": rows}, "footer": "f"}
            self.assertTrue(render_compare_card(data, {}).startswith(PNG))

    def test_player_card_manual_code_only(self):
        data = {"name": "stax", "real_name": None, "team": "T1", "country": "대한민국",
                "tiles": [("DPI", "800", False)], "video": None, "gear": [("마우스", "x")],
                "crosshair_rows": [], "crosshair_raw": {}, "crosshair_code": "0;P;c;5", "manual": True,
                "updated": None, "empty_message": "x"}
        self.assertTrue(render_player_card(data, {}).startswith(PNG))

    def test_player_card_without_settings(self):
        data = {"name": "stax", "tiles": [], "gear": [], "crosshair_rows": [], "empty_message": "없음"}
        self.assertTrue(render_player_card(data, {}).startswith(PNG))


def _import_scheduler():
    """scheduler 는 DB/서비스 모듈을 불러오므로, 그 부분만 가짜로 바꾸고 불러온다."""
    import sys
    from unittest.mock import MagicMock

    fakes = {name: MagicMock() for name in
             ("bot.database.database", "bot.services", "bot.services.match_service", "bot.services.team_service")}
    saved = {k: sys.modules.get(k) for k in fakes}
    sys.modules.update(fakes)
    sys.modules.pop("bot.scheduler", None)
    try:
        from bot import scheduler
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return scheduler


EVENT_HTML = """
<div class="event-header"><div class="event-header-thumb"><div class="wf-avatar"><div><img src="//owcdn.net/img/e.png"></div></div></div>
<h1 class="event-header-main-title"> Valorant Champions 2026 </h1></div>
<div class="event-brackets-container"><div class="bracket-container mod-upper">
<div class="bracket-col mod-1"><div class="bracket-col-label"> Upper Quarterfinals </div>
<div class="bracket-row mod-1"><a class="bracket-item " href="/754732/nrg-vs-t1-valorant-champions-2026-ubqf">
<div class="bracket-item-team mod-first mod-winner "><div class="bracket-item-team-name"><img src="//owcdn.net/img/a.png"><span>NRG</span></div><div class="bracket-item-team-score"> 2 </div></div>
<div class="bracket-item-team mod-loser "><div class="bracket-item-team-name"><img src="//owcdn.net/img/b.png"><span>T1</span></div><div class="bracket-item-team-score"> 0 </div></div>
<div class=" bracket-item-status moment-tz-convert" data-utc-ts="1791363600"><div><span></span>6:00 pm KST, Oct 7</div></div></a></div></div>
<div class="bracket-col mod-3"><div class="bracket-col-label"> Upper Final </div>
<div class="bracket-row mod-1"><a class="bracket-item mod-last" href="/754736/tbd-valorant-champions-2026-ubf">
<div class="bracket-item-team mod-first "><div class="bracket-item-team-name"><img src="/img/vlr/tmp/vlr.png"><span></span></div><div class="bracket-item-team-score"> </div></div>
<div class="bracket-item-team "><div class="bracket-item-team-name"><img src="/img/vlr/tmp/vlr.png"><span></span></div><div class="bracket-item-team-score"> </div></div>
<div class=" bracket-item-status moment-tz-convert" data-utc-ts="1792130400"><div><span></span>3:00 pm KST, Oct 16</div></div></a></div></div>
</div></div>
"""

SEARCH_HTML = """
<a href="/search/r/event/2765/idx" class="wf-module-item search-item mod-first"><div class="search-item-thumb"><img src="//owcdn.net/img/x.png"></div>
<div style="flex: 1;"><div class="search-item-title"> Valorant Masters London 2026 </div>
<div class="search-item-desc ge-text-light"> Jun 6, 2026 to Jun 21, 2026 ⋅ <span>$1,000,000</span> </div></div></a>
"""


class BracketTest(unittest.TestCase):
    def test_parse_bracket(self):
        br = parse_event_bracket(EVENT_HTML, 2766)
        self.assertEqual(br.name, "Valorant Champions 2026")
        self.assertEqual(len(br.sections), 1)
        self.assertEqual(br.sections[0].kind, "upper")
        cols = br.sections[0].columns
        self.assertEqual([c.label for c in cols], ["Upper Quarterfinals", "Upper Final"])
        done, tbd = cols[0].matches[0], cols[1].matches[0]
        self.assertEqual((done.team1.name, done.team1.score, done.team1.winner), ("NRG", 2, True))
        self.assertEqual((done.team2.name, done.team2.score, done.team2.loser), ("T1", 0, True))
        self.assertEqual(done.match_id, 754732)
        self.assertEqual(done.scheduled_at.isoformat(), "2026-10-07T09:00:00+00:00")  # = 한국 시간 오후 6시
        self.assertEqual((tbd.team1.name, tbd.team1.score, tbd.team1.logo_url), ("", None, None))  # 미정 + 기본 이미지 제외

    def test_no_bracket_ok_but_broken_page_raises(self):
        html = '<h1 class="event-header-main-title">Group Event</h1>'
        self.assertEqual(parse_event_bracket(html, 1).sections, [])
        with self.assertRaises(ParseError):
            parse_event_bracket("<html></html>", 1)

    def test_search_events(self):
        r = parse_search_events(SEARCH_HTML)
        self.assertEqual((r[0].vlr_id, r[0].name), (2765, "Valorant Masters London 2026"))
        self.assertEqual(r[0].start.year, 2026)

    def test_query_and_ranking(self):
        from datetime import datetime, timezone

        from bot.scrapers.vlr import EventSearchResult
        from bot.services import event_service as es

        self.assertEqual(es.to_query("마스터스 런던"), "masters london")
        self.assertEqual(es.to_query("챔피언스 2026"), "champions 2026")
        now = datetime.now(timezone.utc)
        old = EventSearchResult(1, "Champions 2023", datetime(2023, 8, 1, tzinfo=timezone.utc), "$2,250,000", None)
        small = EventSearchResult(2, "Champions Cup", now, "$1,000", None)
        big = EventSearchResult(3, "Champions 2026", now, "$2,250,000", None)
        self.assertEqual([e.vlr_id for e in sorted([old, small, big], key=es._rank)], [3, 2, 1])

    def test_render_bracket(self):
        def team(n, sc=None, w=False):
            return {"name": n, "score": sc, "winner": w, "loser": False}
        col = {"label": "승자조 8강", "matches": [{"t1": team("A", 2, True), "t2": team(""), "when": "", "live": False}] * 4}
        col2 = {"label": "승자조 4강", "matches": [{"t1": team(""), "t2": team(""), "when": "10월 8일", "live": True}] * 2}
        col3 = {"label": "결승", "matches": [{"t1": team(""), "t2": team(""), "when": "x", "live": False}]}
        data = {"title": "T", "subtitle": "s", "footer": "f", "sections": [{"kind": "upper", "columns": [col, col2, col3]}]}
        self.assertTrue(render_bracket_card(data, {}).startswith(PNG))


class ImageFetchTest(unittest.TestCase):
    """이미지는 조각조각 와도 끝까지 받고, 일시 오류는 다시 시도하고, 404만 캐시한다."""

    def test_chunked_retry_and_cache(self):
        from io import BytesIO

        from PIL import Image

        from bot.render import images

        buf = BytesIO()
        Image.new("RGB", (300, 300), (200, 10, 10)).save(buf, "PNG")
        data, calls = buf.getvalue(), {"n": 0}

        class Resp:
            def __init__(self, status, body=b""):
                self.status, self.body, self.content = status, body, self

            async def iter_chunked(self, n):
                for i in range(0, len(self.body), 1000):
                    yield self.body[i:i + 1000]

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class Sess:
            def get(self, url):
                calls["n"] += 1
                if "flaky" in url and calls["n"] == 1:
                    return Resp(503)
                return Resp(404) if "gone" in url else Resp(200, data)

        async def fake_session():
            return Sess()

        images._CACHE.clear()
        old = images._get_session
        images._get_session = fake_session
        try:
            async def run():
                full = await images.fetch_image("https://x/a.png")
                calls["n"] = 0
                flaky = await images.fetch_image("https://x/flaky.png")
                gone = await images.fetch_image("https://x/gone.png")
                return full, flaky, gone, calls["n"]

            full, flaky, gone, n = asyncio.run(run())
        finally:
            images._get_session = old
        self.assertIsNotNone(full)
        self.assertIsNotNone(flaky)   # 첫 요청 503 → 재시도로 성공
        self.assertIsNone(gone)
        self.assertIn("https://x/gone.png", images._CACHE)       # 404는 캐시
        self.assertNotIn("https://x/flaky.png-none", images._CACHE)


class SchedulerLiveJobTest(unittest.TestCase):
    def test_live_then_ended_then_idle(self):
        scheduler = _import_scheduler()

        scheduler._live_ids = set()
        scheduler.vlr = NS(fetch_upcoming_matches=AsyncMock())
        scheduler.match_service = NS(get_match_detail=AsyncMock())

        async def run():
            scheduler.vlr.fetch_upcoming_matches.return_value = [NS(vlr_id=1, status="live"), NS(vlr_id=2, status="upcoming")]
            await scheduler.job_live()
            first = [c.args[0] for c in scheduler.match_service.get_match_detail.call_args_list]
            scheduler.match_service.get_match_detail.reset_mock()
            scheduler.vlr.fetch_upcoming_matches.return_value = [NS(vlr_id=2, status="upcoming")]
            await scheduler.job_live()  # 1번 경기가 방금 끝남 → 최종 기록 한 번 더 저장
            second = [c.args[0] for c in scheduler.match_service.get_match_detail.call_args_list]
            scheduler.match_service.get_match_detail.reset_mock()
            await scheduler.job_live()  # 진행 중도 방금 끝난 경기도 없음 → DB 안 건드림
            return first, second, scheduler.match_service.get_match_detail.call_count

        first, second, third = asyncio.run(run())
        self.assertEqual(first, [1])
        self.assertEqual(second, [1])
        self.assertEqual(third, 0)

    def test_fetch_failure_keeps_state(self):
        scheduler = _import_scheduler()

        scheduler._live_ids = {7}
        scheduler.vlr = NS(fetch_upcoming_matches=AsyncMock(side_effect=RuntimeError("boom")))
        asyncio.run(scheduler.job_live())  # 예외가 밖으로 나오지 않음
        self.assertEqual(scheduler._live_ids, {7})

PLAYER_HTML = """
<div class="player-header"><div class="wf-avatar mod-player"><div><img src="//owcdn.net/img/aa.png" alt="f0rsakeN"></div></div>
<div><div><h1 class="wf-title">
  f0rsakeN </h1><h2 class="player-real-name ge-text-light">Jason Susanto</h2></div>
<div class="ge-text-light"><i class="flag mod-id"></i> INDONESIA </div></div></div>
<a class="wf-module-item mod-first" href="/team/624/paper-rex"><div><img src="//owcdn.net/img/bb.png"></div>
<div><div style="font-weight: 500;"> Paper Rex </div><div class="ge-text-light">joined in February 2021</div></div></a>
<table class="wf-table st-table mod-agent-rows"><thead><tr><th>Agent</th></tr></thead><tbody>
<tr><td class="mod-agent"><img src="/img/vlr/game/agents/omen.png" alt="omen"></td><td class="mod-use">(17) 65%</td>
<td>386</td><td>0.95</td><td>190.9</td><td>0.95</td><td>71%</td><td>127.2</td><td>0.68</td><td>0.34</td><td>0.83</td>
<td>264</td><td>279</td><td>133</td><td>30</td><td>36</td></tr>
<tr><td class="mod-agent"><img src="/img/vlr/game/agents/jett.png" alt="jett"></td><td class="mod-use">(9) 35%</td>
<td>200</td><td>1.12</td><td>230.0</td><td>1.20</td><td>74%</td><td>150.0</td><td>0.80</td><td>0.20</td><td>0.10</td>
<td>160</td><td>130</td><td>40</td><td>20</td><td>12</td></tr></tbody></table>
"""


class PlayerStatsTest(unittest.TestCase):
    def test_parse(self):
        page = parse_player_page(PLAYER_HTML, 9801, "90d")
        self.assertEqual(page.nickname, "f0rsakeN")
        self.assertEqual(page.real_name, "Jason Susanto")
        self.assertEqual(page.country_code, "id")
        self.assertEqual(page.team_name, "Paper Rex")
        self.assertEqual(page.team_id, 624)
        self.assertEqual(len(page.agents), 2)
        a = page.agents[0]
        self.assertEqual((a.agent, a.uses, a.use_pct, a.rounds), ("omen", 17, 65, 386))
        self.assertEqual((a.rating, a.acs, a.kd, a.kast, a.adr), (0.95, 190.9, 0.95, 71, 127.2))
        self.assertEqual((a.kills, a.deaths, a.assists, a.fk, a.fd), (264, 279, 133, 30, 36))

    def test_empty_period(self):
        html = PLAYER_HTML.split("<table")[0] + "<div>No agent data available for this period</div>"
        self.assertEqual(parse_player_page(html, 1).agents, [])

    def test_bad_page(self):
        with self.assertRaises(ParseError):
            parse_player_page("<html></html>", 1)

    def test_card_data_and_render(self):
        data = player_stats_data(parse_player_page(PLAYER_HTML, 9801))
        self.assertEqual(data["summary"]["kda"], "424/409/173")
        self.assertEqual(data["rows"][0]["agent"], "Omen")
        png = render_player_stats_card(data, {})
        self.assertTrue(png.startswith(b"\x89PNG"))
        data["rows"] = []
        self.assertTrue(render_player_stats_card(data, {}).startswith(b"\x89PNG"))


class AutocompleteMatchTest(unittest.TestCase):
    def test_match(self):
        from bot.autocomplete import _Entry, match

        entries = [_Entry("Gen.G", ["geng", "젠지"]), _Entry("Team Liquid", ["teamliquid", "tl"]),
                   _Entry("T1", ["t1", "티원"])]
        self.assertEqual(match(entries, "젠"), ["Gen.G"])
        self.assertEqual(match(entries, "T"), ["Team Liquid", "T1"])
        self.assertEqual(match(entries, "liq"), ["Team Liquid"])
        self.assertEqual(len(match(entries, "")), 3)
        self.assertEqual(match(entries, "zzz"), [])


class ScheduleCardTest(unittest.TestCase):
    ROWS = [
        {"tag1": "NRG", "tag2": "T1", "team1": "NRG", "team2": "T1", "score1": 1, "score2": 0, "status": "live",
         "time": "18:00 KST", "time_utc": "09:00 UTC", "stage": "VCT Champions · 8강", "logo1": "a", "logo2": "b"},
        {"tag1": "PRX", "tag2": "LOUD", "team1": "Paper Rex", "team2": "LOUD", "score1": None, "score2": None,
         "status": "upcoming", "time": "21:00 KST", "time_utc": "12:00 UTC", "stage": "VCT Champions", "logo1": "a", "logo2": "b"},
        {"tag1": "NSRF", "tag2": "TALON", "team1": "Nongshim RedForce", "team2": "Talon", "score1": 2, "score2": 1,
         "status": "completed", "time": "15:00 KST", "time_utc": "06:00 UTC", "stage": "", "logo1": "a", "logo2": "b"},
    ]

    def test_render(self):
        for rows, more, ev in ((self.ROWS, "외 3경기", "VCT Champions Shanghai 2026"), ([], None, "")):
            png = render_schedule_card({"event": ev, "title_sub": "오늘의 경기", "date": "10월 7일 (수)",
                                        "rows": rows, "more": more, "footer": "f"}, {})
            self.assertTrue(png.startswith(b"\x89PNG"))


class LogoLightenTest(unittest.TestCase):
    @staticmethod
    def _logo(fill, size=60):
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([5, 5, size - 5, size - 5], fill=fill)
        return img

    def test_black_logo_becomes_white(self):
        out = lighten_dark_logo(self._logo((5, 5, 5, 255)))
        self.assertGreater(out.getpixel((30, 30))[0], 200)
        self.assertEqual(out.getpixel((1, 1))[3], 0)  # 투명 부분 유지

    def test_colored_logo_unchanged(self):
        src = self._logo((230, 40, 60, 255))
        self.assertEqual(lighten_dark_logo(src).getpixel((30, 30)), (230, 40, 60, 255))

    def test_deep_red_logo_unchanged(self):
        src = self._logo((200, 16, 46, 255))   # 농심 같은 진한 빨강: 휘도는 낮지만 검정이 아니다
        self.assertEqual(lighten_dark_logo(src).getpixel((30, 30)), (200, 16, 46, 255))

    def test_dark_navy_logo_becomes_white(self):
        self.assertGreater(lighten_dark_logo(self._logo((15, 22, 60, 255))).getpixel((30, 30))[0], 200)

    def test_light_logo_unchanged(self):
        self.assertEqual(lighten_dark_logo(self._logo((250, 250, 250, 255))).getpixel((30, 30))[:3], (250, 250, 250))


class EmojiTest(unittest.TestCase):
    def test_names(self):
        from bot.services.emoji_service import emoji_name

        self.assertEqual(emoji_name("Gen.G"), "team_gen_g")
        self.assertEqual(emoji_name("T1"), "team_t1")
        self.assertEqual(emoji_name("KRÜ Esports"), "team_kr_esports")
        n = emoji_name("A Very Long Team Name That Keeps Going On And On")
        self.assertLessEqual(len(n), 32)
        self.assertRegex(n, r"^[0-9a-z_]{2,32}$")

    def test_prepare_png(self):
        from io import BytesIO

        from PIL import Image

        from bot.services.emoji_service import SIZE, prepare_png

        png = prepare_png(Image.new("RGBA", (300, 100), (255, 0, 0, 255)))
        out = Image.open(BytesIO(png))
        self.assertEqual(out.size, (SIZE, SIZE))
        self.assertLess(len(png), 256 * 1024)
        self.assertEqual(out.getpixel((SIZE // 2, SIZE // 2)), (255, 0, 0, 255))
        self.assertEqual(out.getpixel((SIZE // 2, 2))[3], 0)  # 위아래 여백은 투명


class HelpTest(unittest.TestCase):
    @staticmethod
    def _cmd(name, desc, params=()):
        return NS(name=name, description=desc, parameters=[NS(name=n, required=r) for n, r in params])

    def test_flatten_and_usage(self):
        from bot.embeds.help import flatten, usage

        group = NS(name="관리", description="g", commands=[self._cmd("팀갱신", "d", [("팀", True)])])
        flat = flatten([self._cmd("팀", "팀 조회", [("이름", True)]), group])
        self.assertEqual([f[0] for f in flat], ["팀", "관리 팀갱신"])
        self.assertEqual(usage("선수", [("닉네임", True), ("기간", False)]), "/선수 <닉네임> [기간]")

    def test_sections_admin_visibility(self):
        from bot.embeds.help import help_sections

        cmds = [self._cmd("팀", "팀 조회", [("이름", True)]), self._cmd("새기능", "나중에 추가됨"),
                NS(name="관리", description="g", commands=[self._cmd("상태", "봇 상태")])]
        titles = lambda admin: [t for t, _ in help_sections(cmds, show_admin=admin)]
        self.assertIn("✨ 그 밖의 명령어", titles(False))     # 분류에 없는 새 명령어도 빠지지 않음
        self.assertNotIn("🔒 관리자 전용", titles(False))
        self.assertIn("🔒 관리자 전용", titles(True))
        body = dict(help_sections(cmds, show_admin=False))["📅 경기·팀"]
        self.assertIn("/팀 <이름>", body)


class PlayerCompareTest(unittest.TestCase):
    def test_compare_card(self):
        from bot.render.player_compare_card import compare_data, render_player_compare_card, summarize
        from tests.test_core import PLAYER_HTML

        a = parse_player_page(PLAYER_HTML, 1)
        b = parse_player_page(PLAYER_HTML.replace("f0rsakeN", "Other").replace("0.95", "1.30"), 2)
        s = summarize(a)
        self.assertAlmostEqual(s["kills"], 424.0)
        self.assertGreater(summarize(b)["rating"], s["rating"])
        png = render_player_compare_card(compare_data(a, b), {})
        self.assertTrue(png.startswith(b"\x89PNG"))


def _bet(o1, o2, note="Pre-match"):
    return (f'<a href="/rr/bet/1" class="wf-card mod-dark match-bet-item"><div class="match-bet-item-half mod-1">'
            f'<span class="match-bet-item-team-name">A</span><span class="match-bet-item-odds mod- mod-1">{o1}</span></div>'
            f'<div class="match-bet-item-half mod-2"><span class="match-bet-item-odds mod- mod-2">{o2}</span>'
            f'<span class="match-bet-item-team-name">B</span><div class="match-bet-item-note">{note}</div></div></a>')


class OddsParseTest(unittest.TestCase):
    def test_average_and_probability(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_bet("1.44", "2.66") + _bet("1.44", "2.66") + _bet("1.40", "2.88"), "html.parser")
        o = parse_match_odds(soup)
        self.assertEqual((o.team1_odds, o.team2_odds, o.sources), (1.43, 2.73, 3))
        self.assertTrue(0.6 < o.p1 < 0.7)   # 1.43 쪽이 우세

    def test_ignores_live_and_garbage(self):
        from bs4 import BeautifulSoup

        self.assertIsNone(parse_match_odds(BeautifulSoup(_bet("1.1", "5.0", "Live"), "html.parser")))
        self.assertIsNone(parse_match_odds(BeautifulSoup(_bet("-", "x"), "html.parser")))
        self.assertIsNone(parse_match_odds(BeautifulSoup("<div></div>", "html.parser")))


class OddsModelTest(unittest.TestCase):
    def test_wins_needed(self):
        from bot.services.odds_model import wins_needed

        self.assertEqual([wins_needed(x) for x in ("BO1", "BO3", "BO5", None, "")], [1, 2, 3, None, None])

    def test_map_prob_roundtrip(self):
        from bot.services.odds_model import map_win_prob, series_win_prob

        for n in (2, 3):
            for p in (0.2, 0.5, 0.68, 0.9):
                self.assertAlmostEqual(series_win_prob(map_win_prob(p, n), n), p, places=6)

    def test_score_options_probabilities_sum_to_one(self):
        from bot.services.odds_model import HOUSE_EDGE, score_options

        for bo, count in (("BO3", 4), ("BO5", 6)):
            opts = score_options(0.65, bo)
            self.assertEqual(len(opts), count)
            # 배율 = 0.95/확률 → 확률 합이 1 이어야 한다 (상·하한에 걸린 항목이 없는 범위)
            self.assertAlmostEqual(sum((1 - HOUSE_EDGE) / m for _, m in opts), 1.0, delta=0.08)
        self.assertEqual(score_options(0.5, "BO1"), [])
        favorite = dict(score_options(0.8, "BO3"))
        self.assertLess(favorite["2-0"], favorite["0-2"])   # 우세 팀의 2:0 이 더 낮은 배율

    def test_mvp_multiplier(self):
        from bot.services.odds_model import mvp_multiplier

        self.assertLess(mvp_multiplier(0.8), mvp_multiplier(0.5))   # 우세 팀 선수가 낮은 배율
        self.assertLess(mvp_multiplier(0.5), mvp_multiplier(0.2))
        self.assertTrue(3.0 <= mvp_multiplier(0.99) <= 30.0)

    def test_build_odds_fallback_and_payout(self):
        from bot.services.odds_model import build_odds, payout

        o = build_odds(None)
        self.assertEqual((o.winner, o.from_vlr, o.team1_p), ((1.9, 1.9), False, 0.5))
        self.assertEqual(payout(100, 1.43), 143)
        self.assertEqual(payout(15, 1.9), 28)   # 28.5 → 버림

    def test_betting_state(self):
        from datetime import datetime, timedelta, timezone

        from bot.services.odds_model import betting_state

        start = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        at = lambda m: betting_state(start + timedelta(minutes=m), start, "upcoming")  # noqa: E731
        self.assertEqual((at(-60), at(-10.01), at(-10), at(-1), at(0), at(5)), ("open", "open", "locked", "locked", "started", "started"))
        self.assertEqual(betting_state(start, start, "live"), "started")
        self.assertEqual(betting_state(start, None, "upcoming"), "unknown")

    def test_mvp_and_settle(self):
        from bot.services.odds_model import mvp_of, settle_outcome

        P = lambda n, r, a: NS(name=n, rating=r, acs=a)  # noqa: E731
        stats = [[P("Meteor", "1.20", "250"), P("aspas", "1.20", "260")], [P("Derrek", "1.05", "200"), P("x", None, None)]]
        self.assertEqual(mvp_of(stats), "aspas")      # 레이팅 동률 → ACS
        self.assertIsNone(mvp_of([]))
        self.assertIsNone(mvp_of([[P("a", "-", "-")]]))
        r = dict(score1=2, score2=1, mvp="aspas")
        self.assertEqual(settle_outcome("winner", "1", **r), "won")
        self.assertEqual(settle_outcome("winner", "2", **r), "lost")
        self.assertEqual(settle_outcome("score", "2-1", **r), "won")
        self.assertEqual(settle_outcome("score", "2-0", **r), "lost")
        self.assertEqual(settle_outcome("mvp", "ASPAS", **r), "won")
        self.assertEqual(settle_outcome("mvp", "Meteor", **r), "lost")
        self.assertEqual(settle_outcome("mvp", "Meteor", score1=2, score2=1, mvp=None), "void")
        self.assertEqual(settle_outcome("winner", "1", score1=None, score2=None, mvp=None), "void")


class CommandStructureTest(unittest.TestCase):
    def test_commands_are_class_methods(self):
        """명령어 함수가 setup() 안에 잘못 들어가면(들여쓰기 실수) 봇이 시작 때 죽는다."""
        import ast
        import glob

        for path in glob.glob("bot/commands/*.py"):
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in tree.body:
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "setup":
                    nested = [n.name for n in ast.walk(node) if isinstance(n, ast.AsyncFunctionDef) and n is not node]
                    self.assertEqual(nested, [], path)


class EconomyCommandsTest(unittest.TestCase):
    def test_new_commands_registered_and_named_lowercase(self):
        import ast
        tree = ast.parse(open("bot/commands/economy.py", encoding="utf-8").read())
        names = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "command":
                for k in n.keywords:
                    if k.arg == "name":
                        names.append(k.value.value)
        self.assertEqual(set(names), {"vp", "출석", "vp랭킹", "예측", "내예측", "예측현황", "출첵", "ㅊㅊ"})
        for nm in names:
            self.assertEqual(nm, nm.lower())
        self.assertIn("bot.commands.economy", open("bot/commands/__init__.py", encoding="utf-8").read())


class GamesTest(unittest.TestCase):
    def test_slot_rtp(self):
        from bot.services import games
        self.assertTrue(0.93 < games.slot_rtp() < 0.97)

    def test_dice_and_coin_payouts(self):
        from bot.services import games
        self.assertEqual(games.dice_payout("홀", 3, 100), 195)
        self.assertEqual(games.dice_payout("짝", 3, 100), 0)
        self.assertEqual(games.dice_payout("4", 4, 100), 570)

    def test_hand_value(self):
        from bot.services import games
        self.assertEqual(games.hand_value(["A♠", "K♥"]), 21)
        self.assertEqual(games.hand_value(["A♠", "A♥", "9♦"]), 21)
        self.assertEqual(games.hand_value(["K♠", "Q♥", "5♦"]), 25)

    def test_blackjack_results(self):
        import random
        from bot.services import games
        g = games.Blackjack(stake=100, deck=["7♣", "K♠", "K♥", "A♠"])
        # 플레이어 A♠ K♥ = 블랙잭 (pop 순서: A♠, K♥ / 딜러 K♠, 7♣)
        self.assertEqual(g.result(), ("blackjack", 250))
        for seed in range(200):   # 어떤 판이든 지급액은 0 ~ 2.5배
            g = games.Blackjack(stake=100, deck=games.new_deck(random.Random(seed)))
            if not g.done:
                g.stand()
            outcome, pay = g.result()
            self.assertIn(pay, (0, 100, 200, 250))

    def test_quiz_bank_valid(self):
        from bot.services import quiz_bank
        for q, a, wrong in quiz_bank.QUESTIONS:
            self.assertEqual(len(set(wrong)), 3)
            self.assertNotIn(a, wrong)
        _, _, options, ans = quiz_bank.pick_question()
        self.assertEqual(len(options), 4)

    def test_week_start_is_monday(self):
        from datetime import datetime
        from bot.services import quiz_bank
        ws = quiz_bank.week_start(datetime(2026, 10, 8, 15, 30))
        self.assertEqual((ws.weekday(), ws.hour), (0, 0))


class TeamMapsTest(unittest.TestCase):
    ROW = ("<tr><td>{n} ({g})</td><td></td><td>{w}%</td><td>{wi}</td><td>{lo}</td><td>4</td><td>5</td>"
           "<td>52%</td><td>10</td><td>9</td><td>55%</td><td>11</td><td>8</td><td>x</td></tr>")

    def html(self):
        rows = self.ROW.format(n="Bind", g=9, w=56, wi=5, lo=4) + self.ROW.format(n="Icebox", g=0, w="-", wi=0, lo=0)
        rows += "<tr><td></td><td>2026/5/02 FULL SENSE 7/13</td><td></td></tr>"
        return f'<table class="wf-table mod-team-maps">{rows}</table>'

    def test_parse(self):
        from bot.scrapers.vlr import parse_team_maps
        got = parse_team_maps(self.html())
        self.assertEqual(len(got), 1)
        m = got[0]
        self.assertEqual((m.map_name, m.games, m.win_pct, m.wins, m.losses, m.atk_win_pct, m.def_win_pct),
                         ("Bind", 9, 56, 5, 4, 52, 55))

    def test_card_renders(self):
        from bot.render.team_maps_card import render_team_maps_card, team_maps_data
        from bot.scrapers.vlr import parse_team_maps
        png = render_team_maps_card(team_maps_data("T1", parse_team_maps(self.html()), "전체 기간"))
        self.assertTrue(png.startswith(b"\x89PNG"))


class GameAnimTest(unittest.TestCase):
    def test_gifs_render(self):
        from bot.render import game_anim as g
        for gif in (g.coin_gif("앞"), g.coin_gif("뒤"), g.dice_gif(3), g.slot_gif(["🍒", "🔥", "💎"]),
                    g.deal_gif(["A♠", "K♥"], ["9♦", "7♣"]), g.finish_gif(["A♠", "K♥", "5♣"], ["10♦", "6♣", "9♥"])):
            self.assertTrue(gif.startswith(b"GIF8"))
            self.assertLess(len(gif), 1_000_000)

    def test_table_and_quiz_image(self):
        from PIL import Image
        from bot.render import game_anim as g
        self.assertTrue(g.table_png(["A♠", "K♥"], ["9♦", "7♣"], True).startswith(b"\x89PNG"))
        art = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
        art.paste((255, 0, 0, 255), (50, 50, 150, 250))
        self.assertTrue(g.quiz_image(art, silhouette=True).startswith(b"\x89PNG"))
        self.assertTrue(g.quiz_image(art, silhouette=False, caption="제트").startswith(b"\x89PNG"))

    def test_quiz_options(self):
        import random
        from bot.services import quiz_assets
        opts, idx = quiz_assets._opts("제트", ["제트", "오멘", "소바", "세이지", "킬조이"], random.Random(1))
        self.assertEqual(len(set(opts)), 4)
        self.assertEqual(opts[idx], "제트")


class ProfileShopTest(unittest.TestCase):
    def test_catalog(self):
        from bot.services import shop_catalog as c
        self.assertEqual(len(c.BY_ID), len(c.ITEMS))
        for kind, default in c.DEFAULTS.items():
            self.assertIn(default, c.FREE_IDS)
            self.assertEqual(c.BY_ID[default].kind, kind)
        self.assertTrue(c.owned_or_free("theme_default", set()))
        self.assertFalse(c.owned_or_free("frame_gold", set()))
        self.assertTrue(c.owned_or_free("frame_gold", {"frame_gold"}))
        self.assertLessEqual(len([i for i in c.ITEMS if i.price > 0]), 25)   # 상점 선택 메뉴 한도

    def test_profile_card_renders(self):
        from bot.render.profile_card import FRAME_COLORS, THEMES, render_profile_card
        base = dict(name="테스트", title="뉴비", vp=1234, rank=1, pred_win=1, pred_total=2, quiz_week=1, quiz_limit=5,
                    fav_team=None, fav_agent="제트")
        for theme in THEMES:
            for frame in ["frame_none", "frame_rainbow", *FRAME_COLORS]:
                self.assertTrue(render_profile_card(dict(base, theme=theme, frame=frame)).startswith(b"\x89PNG"))


class CancelFeeAndChannelTest(unittest.TestCase):
    def test_cancel_fee_is_ten_percent_floor(self):
        from bot.services.odds_model import cancel_fee
        self.assertEqual(cancel_fee(100), 10)
        self.assertEqual(cancel_fee(2000), 200)
        self.assertEqual(cancel_fee(15), 1)      # 소수점 버림
        self.assertEqual(cancel_fee(10), 1)

    def test_game_channel_restriction(self):
        from unittest.mock import patch
        from bot.services import guild_settings as gsx

        def inter(channel_id, admin=False):
            return NS(guild_id=1, channel_id=channel_id, user=NS(id=5, guild_permissions=NS(administrator=admin)))

        class FakeRestricted(Exception):   # discord 스텁에서는 CheckFailure 가 예외 클래스가 아니라서 대체
            def __init__(self, channel_id):
                self.channel_id = channel_id

        with patch.object(gsx, "ChannelRestricted", FakeRestricted), patch.object(gsx, "get", AsyncMock(return_value=(100, None))):
            self.assertTrue(asyncio.run(gsx.check_game_channel(inter(100))))            # 게임 채널
            self.assertTrue(asyncio.run(gsx.check_game_channel(inter(7, admin=True))))  # 관리자는 예외
            with self.assertRaises(FakeRestricted) as ctx:
                asyncio.run(gsx.check_game_channel(inter(7)))
            self.assertEqual(ctx.exception.channel_id, 100)
        with patch.object(gsx, "get", AsyncMock(return_value=(None, None))):            # 설정 없으면 어디서나
            self.assertTrue(asyncio.run(gsx.check_game_channel(inter(7))))


class StockModelTest(unittest.TestCase):
    def test_catalog(self):
        from bot.services import stock_model as sm
        self.assertEqual(len(sm.STOCKS), 6)
        self.assertEqual(len({d.symbol for d in sm.STOCKS}), 6)
        self.assertEqual(len({d.vlr_id for d in sm.STOCKS}), 6)
        self.assertIn("VL", sm.BY_SYMBOL)
        self.assertIn("KRX", sm.BY_SYMBOL)

    def test_fee_and_totals(self):
        from bot.services import stock_model as sm
        self.assertEqual(sm.fee(100), 1)
        self.assertEqual(sm.fee(150), 2)          # 올림
        self.assertEqual(sm.fee(1), 1)            # 최소 1
        self.assertEqual(sm.buy_total(200, 10), (2000, 20))
        self.assertEqual(sm.sell_proceeds(200, 10), (1980, 20))

    def test_price_stays_in_band_and_moves(self):
        import random
        from bot.services import stock_model as sm
        self.assertEqual(sm.apply_move(100, 100, 0.0001), 101)          # 반올림으로 안 움직이면 최소 1
        self.assertEqual(sm.apply_move(26, 100, -0.5), 25)              # 바닥 25%
        self.assertEqual(sm.apply_move(390, 100, 0.5), 400)             # 천장 400%
        rng = random.Random(1)
        p = 100
        for _ in range(5000):
            p = sm.noise_step(p, 100, rng)
            self.assertTrue(25 <= p <= 400)
        # 평균 회귀: 기준가보다 많이 낮은 가격은 평균적으로 올라온다
        ups = sum(sm.noise_step(50, 100, random.Random(i)) > 50 for i in range(200))
        self.assertGreater(ups, 120)

    def test_next_tick_is_top_of_next_hour(self):
        from datetime import datetime, timedelta, timezone
        from bot.services.stock_model import next_tick_at
        kst = timezone(timedelta(hours=9))
        self.assertEqual(next_tick_at(datetime(2026, 10, 8, 18, 10, 5, tzinfo=kst)), datetime(2026, 10, 8, 19, 0, tzinfo=kst))
        self.assertEqual(next_tick_at(datetime(2026, 10, 8, 23, 59, tzinfo=kst)), datetime(2026, 10, 9, 0, 0, tzinfo=kst))
        self.assertEqual(next_tick_at(datetime(2026, 10, 8, 18, 0, tzinfo=kst)), datetime(2026, 10, 8, 19, 0, tzinfo=kst))

    def test_position_math(self):
        from bot.services.stock_model import Position
        p = Position("GEN", "젠지", 10, 100.0, 120)
        self.assertEqual((p.value, p.pnl), (1200, 200))
        self.assertAlmostEqual(p.pnl_pct, 20.0)

    def test_board_card_renders(self):
        from bot.render.stock_card import render_stock_board
        from bot.services.stock_model import Quote
        q = [Quote("GEN", "젠지", 300, 3.0, [290, 300]), Quote("T1", "티원", 250, None, [250])]
        self.assertTrue(render_stock_board(q).startswith(b"\x89PNG"))



if __name__ == "__main__":
    unittest.main()


class StockRankingTest(unittest.TestCase):
    def test_rank_by_pnl(self):
        from bot.services import stock_model as sm

        base = sm.STOCKS[0]
        prices = {base.symbol: 1000}
        # 유저1: 10주를 평균 800에 → +2000 / 유저2: 10주를 1200에 → -2000 / 유저3: 모르는 종목은 무시
        rows = [(1, base.symbol, 10, 8000), (2, base.symbol, 10, 12000), (3, "ZZZ", 5, 100), (4, base.symbol, 0, 0)]
        ranked = sm.rank_investors(rows, prices)
        self.assertEqual([r[0] for r in ranked], [1, 2])
        self.assertEqual(ranked[0][1:3], (10000, 2000))
        self.assertAlmostEqual(ranked[0][3], 25.0)
        self.assertEqual(ranked[1][2], -2000)

    def test_chart_renders(self):
        from bot.render.stock_chart import render_stock_chart

        for single in (True, False):
            png = render_stock_chart({"젠지": [1000, 1020, 990, 1050], "T1": [1200, 1180, 1250]}, "t", single=single)
            self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(render_stock_chart({"젠지": [1000]}, "t", single=True).startswith(b"\x89PNG"))


class PrewarmTest(unittest.TestCase):
    def test_jobs_cover_coin_dice_slot(self):
        from bot.render import game_anim

        jobs = game_anim.prewarm_jobs()
        v = game_anim.VARIANTS
        self.assertEqual(len(jobs), 2 * v + 6 * v + 5 * v)
        jobs[0]()  # 실제로 만들어져 캐시에 들어간다
        before = game_anim._coin_cached.cache_info().hits
        game_anim._coin_cached("앞", 0)
        self.assertEqual(game_anim._coin_cached.cache_info().hits, before + 1)


class MatchAlertTest(unittest.TestCase):
    def test_schedules_once_and_skips_tbd(self):
        from datetime import datetime, timedelta, timezone

        scheduler = _import_scheduler()
        now = datetime.now(timezone.utc)

        def m(i, mins, t1="A", t2="B", status="upcoming"):
            return NS(vlr_id=i, status=status, scheduled_at=now + timedelta(minutes=mins), team1_name=t1, team2_name=t2,
                      tournament_name="T")

        rows = [m(1, 50), m(2, 50, t2="TBD"), m(3, 5), m(4, 50, status="live"), m(5, 20)]
        added = []
        scheduler._scheduler = NS(add_job=lambda *a, **k: added.append((k["id"], k["run_date"])))
        scheduler.broadcaster = AsyncMock()
        scheduler.prediction_service = NS(is_tbd=lambda n: not n or n.strip().upper() == "TBD")
        scheduler._alerted = set()
        import sys
        import bot.database as dbpkg

        fake_repo = NS(get_matches_between=AsyncMock(return_value=rows))
        sys.modules["bot.database.repository"] = fake_repo
        dbpkg.repository = fake_repo

        class _Ctx:
            async def __aenter__(self): return None
            async def __aexit__(self, *a): return False

        scheduler.db = NS(session=lambda: _Ctx())
        asyncio.run(scheduler._schedule_alerts())
        asyncio.run(scheduler._schedule_alerts())   # 두 번째에는 새로 예약하지 않는다
        ids = [i for i, _ in added]
        self.assertEqual(ids, ["alert-1", "alert-5"])
        self.assertAlmostEqual((added[0][1] - (rows[0].scheduled_at - timedelta(minutes=30))).total_seconds(), 0, delta=1)
        self.assertGreater(added[1][1], now)   # 이미 30분 안이면 곧바로(몇 초 뒤)
        scheduler._scheduler = None
        sys.modules.pop("bot.database.repository", None)
        del dbpkg.repository


class SkinCatalogTest(unittest.TestCase):
    def _cat(self):
        from bot.services import skin_service as ss

        weapons = [{"displayName": "밴달", "skins": [
            {"uuid": "s0", "displayName": "기본 밴달", "themeUuid": ss.STANDARD_THEME, "contentTierUuid": None,
             "displayIcon": "u0", "levels": [], "chromas": []},
            {"uuid": "s1", "displayName": "리버 밴달", "themeUuid": "t1", "contentTierUuid": "411e4a55-4e59-7757-41f0-86a53f101bb5", "displayIcon": None,
             "levels": [{"displayIcon": "u1"}] * 3 + [{"displayIcon": "u1", "streamedVideo": "vid"}],
             "chromas": [{"displayName": "리버 밴달", "fullRender": "cd"},
                         {"displayName": "리버 밴달 (보라색)", "fullRender": "c1"}, {"displayName": "리버 밴달 (초록색)", "displayIcon": "c2", "streamedVideo": "v2"},
                         {"displayName": "x", "fullRender": "cd"}, {}]},
            {"uuid": "s2", "displayName": "무작위 선호 스킨", "themeUuid": "t1", "contentTierUuid": "411e4a55-4e59-7757-41f0-86a53f101bb5", "levels": [], "chromas": []}]},
            {"displayName": "근접 무기", "category": "EEquippableCategory::Melee", "skins": [
                {"uuid": "s3", "displayName": "리버 단검", "themeUuid": "t1", "contentTierUuid": "411e4a55-4e59-7757-41f0-86a53f101bb5",
                 "displayIcon": "u3", "levels": [{}], "chromas": []}]}]
        tiers = [{"uuid": "411e4a55-4e59-7757-41f0-86a53f101bb5", "displayName": "얼티밋 에디션", "highlightColor": "f5955cff", "displayIcon": "ti"}]
        themes = [{"uuid": "t1", "displayName": "리버 컬렉션"}]
        bundles = [{"uuid": "b1", "displayName": "리버", "displayNameSubText": "컬렉션", "description": "d", "displayIcon": "bi"},
                   {"uuid": "b2", "displayName": "없는 번들", "displayIcon": None, "displayIcon2": "x"}]
        return ss, ss.parse_catalog(weapons, tiers, themes, bundles)

    def test_weapon_and_tier_listing(self):
        ss, cat = self._cat()
        self.assertEqual(ss.weapon_names(cat), ["밴달", "근접 무기"])     # 근접은 마지막
        self.assertEqual(ss.tier_names(cat, "밴달"), ["얼티밋 에디션"])
        self.assertEqual([s.uuid for s in ss.list_skins(cat, "밴달")], ["s1"])
        self.assertEqual(ss.list_skins(cat, "밴달", "없는 등급"), [])

    def test_parse_filters_and_links(self):
        ss, cat = self._cat()
        self.assertEqual([s.uuid for s in cat.skins], ["s1", "s3"])      # 기본/무작위 스킨 제외
        s = cat.skins[0]
        self.assertEqual((s.icon, s.tier, s.color, s.chromas, s.levels), ("cd", "얼티밋 에디션", 0xF5955C, 2, 4))
        # 기본 색(스킨 이름과 같은 항목)은 하나로 합치고, 같은 이미지·빈 이미지는 제외. 영상은 없으면 스킨 영상으로
        self.assertEqual(s.variants, [("기본", "cd", "vid"), ("보라색", "c1", "vid"), ("초록색", "c2", "v2")])
        self.assertEqual((s.price, s.tier_icon, ss.price_text(s)), (2475, "ti", "2,475 VP"))   # 얼티밋
        self.assertEqual(ss.price_text(cat.skins[1]), "약 4,950 VP")    # 가격표에 없는 근접 무기 → 등급 어림값
        self.assertIn("youtube.com/results", ss.trailer_url("리버"))
        self.assertEqual([x.uuid for x in cat.bundles[0].skins], ["s1", "s3"])   # '리버 컬렉션' 테마 = '리버' 번들
        self.assertEqual([b.uuid for b in cat.bundles], ["b1"])         # 스킨 없는 세트('없는 번들')는 목록에서 제외

    def test_melee_takes_gun_tier(self):
        from bot.services import skin_service as ss
        weapons = [{"displayName": "밴달", "skins": [{"uuid": "g", "displayName": "리버 밴달", "themeUuid": "t1",
                                                     "contentTierUuid": ss.PREMIUM, "displayIcon": "i"}]},
                   {"displayName": "근접 무기", "category": "EEquippableCategory::Melee", "skins": [
                       {"uuid": "m", "displayName": "리버 단검", "themeUuid": "t1", "contentTierUuid": ss.EXCLUSIVE, "displayIcon": "i"}]}]
        tiers = [{"uuid": ss.PREMIUM, "displayName": "프리미엄 에디션"}, {"uuid": ss.EXCLUSIVE, "displayName": "익스클루시브 에디션"}]
        cat = ss.parse_catalog(weapons, tiers, [{"uuid": "t1", "displayName": "리버"}], [], {"m": "Reaver Knife"})
        knife = next(s for s in cat.skins if s.melee)
        self.assertEqual((knife.tier, knife.price, knife.approx), ("프리미엄 에디션", 3550, False))

    def test_exclusive_gun_by_collection(self):
        from bot.services import skin_service as ss
        weapons = [{"displayName": "밴달", "skins": [
            {"uuid": a, "displayName": f"{n} 밴달", "themeUuid": a, "contentTierUuid": ss.EXCLUSIVE, "displayIcon": "i"}
            for a, n in (("k", "쿠로나미"), ("c", "2023 챔피언스"), ("v", "VCT x T1"), ("z", "모르는"))]}]
        themes = [{"uuid": a, "displayName": n} for a, n in (("k", "쿠로나미"), ("c", "2023 챔피언스"), ("v", "VCT x T1"), ("z", "모르는"))]
        cat = ss.parse_catalog(weapons, [{"uuid": ss.EXCLUSIVE, "displayName": "익스"}], themes, [])
        got = {s.uuid: (s.price, s.approx, s.capsule) for s in cat.skins}
        self.assertEqual(got, {"k": (2375, False, False), "c": (2675, False, False),
                               "v": (None, False, True), "z": (2175, True, False)})

    def test_blank_set_image_is_skipped(self):
        from PIL import Image
        from bot.services import skin_service as ss
        self.assertTrue(ss.is_blank(Image.new("RGBA", (4, 4), (0, 0, 0, 0))))
        self.assertFalse(ss.is_blank(Image.new("RGBA", (4, 4), (9, 9, 9, 255))))
        self.assertFalse(ss.is_blank(Image.new("RGB", (4, 4))))

    def test_melee_and_exclusive_prices(self):
        from bot.services import skin_service as ss
        self.assertEqual(ss.skin_price(ss.PREMIUM, True, "Reaver Knife"), (3550, False))
        self.assertEqual(ss.skin_price(ss.EXCLUSIVE, True, "Champions 2023 Kunai"), (5350, False))
        self.assertEqual(ss.skin_price(ss.ULTRA, True, "RGX 11z Pro Blade"), (4350, False))   # 띄어쓰기·대소문자 무시
        self.assertEqual(ss.skin_price(ss.EXCLUSIVE, False), (2175, True))
        self.assertEqual(ss.skin_price(ss.SELECT, False), (875, False))
        self.assertEqual(ss.skin_price(None, True, "Reaver Knife"), (None, False))          # 배틀패스 등

    def test_search(self):
        ss, cat = self._cat()
        self.assertEqual([s.uuid for s in ss.search_skins(cat, "리버 밴달")], ["s1"])
        self.assertEqual([s.uuid for s in ss.search_skins(cat, "밴달 리버")], ["s1"])
        self.assertEqual(len(ss.search_skins(cat, "리버")), 2)
        self.assertEqual(cat.skins[0].variants[0][:2], ("기본", "cd"))
        self.assertEqual(ss.search_skins(cat, "없음없음"), [])
        self.assertEqual([b.uuid for b in ss.search_bundles(cat, "리")], ["b1"])


class SkinDisambiguateTest(unittest.TestCase):
    def test_same_name_gets_label(self):
        from bot.services import skin_service as ss

        mk = lambda u, th, w="밴달": ss.Skin(u, "프라임 밴달", w, "t", None, None, th, 0, 0)
        a, b, c = mk("1", "프라임"), mk("2", "프라임 2.0"), mk("3", "프라임")
        d = ss.Skin("4", "단독", "밴달", None, None, None, None, 0, 0)
        ss._disambiguate([a, b, d])
        self.assertEqual((a.label, b.label, d.label), ("프라임 밴달 (프라임)", "프라임 밴달 (프라임 2.0)", "단독"))
        ss._disambiguate([a, c])
        self.assertEqual((a.label, c.label), ("프라임 밴달 (1)", "프라임 밴달 (2)"))


class DuplicateBundleTest(unittest.TestCase):
    def _parse(self, bundles):
        from bot.services import skin_service as ss

        mk = lambda u, n, th: {"uuid": u, "displayName": n, "themeUuid": th, "contentTierUuid": None, "displayIcon": "i", "levels": [], "chromas": []}
        weapons = [{"displayName": "밴달", "skins": [mk("a", "RGX 밴달", "t1"), mk("b", "RGX 2.0 밴달", "t2")]}]
        themes = [{"uuid": "t1", "displayName": "RGX 컬렉션"}, {"uuid": "t2", "displayName": "RGX 2.0 컬렉션"}]
        return ss.parse_catalog(weapons, [], themes, bundles)

    def test_same_name_keeps_one(self):
        cat = self._parse([{"uuid": "b1", "displayName": "RGX"}, {"uuid": "b2", "displayName": "RGX", "extraDescription": "RGX 2.0 판"},
                           {"uuid": "b3", "displayName": "RGX"}, {"uuid": "b4", "displayName": "프라임"}])
        self.assertEqual([b.uuid for b in cat.bundles], ["b1"])      # 스킨 수가 같으면 버전 표기 없는 원본, 먼저 나온 것 (b4는 스킨 없음)
        self.assertEqual([s.uuid for s in cat.bundles[0].skins], ["a"])

    def test_prefers_more_skins(self):
        cat = self._parse([{"uuid": "b1", "displayName": "없는 컬렉션"}, {"uuid": "b2", "displayName": "RGX 2.0"}, {"uuid": "b3", "displayName": "RGX"}])
        self.assertNotIn("b1", [b.uuid for b in cat.bundles])      # 스킨 없음 → 제외

    def test_excluded_names(self):
        cat = self._parse([{"uuid": "x1", "displayName": "RGX 역습"}, {"uuid": "x2", "displayName": "VCT 클래식 RGX"},
                           {"uuid": "x3", "displayName": "RGX 팀 캡슐"}, {"uuid": "x4", "displayName": "RGX", "displayNameSubText": "자선 판매"},
                           {"uuid": "ok", "displayName": "RGX"}, {"uuid": "ok2", "displayName": "RGX 2.0", "displayNameSubText": "VCT 2026"}])
        self.assertEqual([b.uuid for b in cat.bundles], ["ok", "ok2"])     # VCT 연도 칼 세트는 남기고 클래식만 제외


class IconUrlTest(unittest.TestCase):
    def test_candidates_end_with_skin_icon(self):
        from bot.services import skin_service as ss

        sk = ss.Skin("s", "n", "w", None, None, "skin-icon", None, 0, 0)
        b = ss.Bundle("b", "n", None, None, "big", [sk], icons=["small", "big"])
        self.assertEqual(ss.icon_urls(b), ["small", "big", "skin-icon"])
        self.assertEqual(ss.icon_urls(ss.Bundle("b", "n", None, None, None, [sk])), ["skin-icon"])
        self.assertEqual(ss.icon_urls(ss.Bundle("b", "n", None, None, None, [])), [])


class ThemeTokenMatchTest(unittest.TestCase):
    def test_word_order_and_dropped(self):
        from bot.services import skin_service as ss

        sk = {"uuid": "a", "displayName": "챔피언스 2023 밴달", "themeUuid": "t", "contentTierUuid": None, "displayIcon": "i", "levels": [], "chromas": []}
        cat = ss.parse_catalog([{"displayName": "밴달", "skins": [sk]}], [], [{"uuid": "t", "displayName": "2023 챔피언스 컬렉션"}],
                               [{"uuid": "b1", "displayName": "챔피언스 2023"}, {"uuid": "b2", "displayName": "듀오의 하루"},
                                {"uuid": "b3", "displayName": "팀 캡슐"}])
        self.assertEqual([[s.uuid for s in b.skins] for b in cat.bundles], [["a"]])
        self.assertEqual(dict(cat.dropped), {"듀오의 하루": "스킨 없음", "팀 캡슐": "제외 규칙"})


class SetTierTest(unittest.TestCase):
    def test_majority_tier_then_price(self):
        from bot.services import skin_service as ss

        mk = lambda tier, price: ss.Skin("s", "n", "w", tier, None, None, None, 0, 0, price=price)
        b = ss.Bundle("b", "n", None, None, None, [mk("프리미엄 에디션", 1775), mk("얼티밋 에디션", 2175), mk("얼티밋 에디션", None)])
        self.assertEqual(ss.set_tier(b).tier, "얼티밋 에디션")
        b2 = ss.Bundle("b", "n", None, None, None, [mk("프리미엄 에디션", 1775), mk("얼티밋 에디션", 2175)])
        self.assertEqual(ss.set_tier(b2).tier, "얼티밋 에디션")          # 같은 수면 더 비싼 쪽
        self.assertIsNone(ss.set_tier(ss.Bundle("b", "n", None, None, None, [])))
        self.assertEqual(ss.short_tier("얼티밋 에디션"), "얼티밋")


class SetSortTest(unittest.TestCase):
    def test_numbers_then_english_then_korean(self):
        from bot.services.skin_service import sort_key

        names = ["프라임", "RGX 11z", "10 스킨", "2025 챔피언스", "2 스킨", "//2.0 아이온", "ABC", "가이아", "넵튠", "rgx 2"]
        got = sorted(names, key=sort_key)
        self.assertEqual(got, ["2 스킨", "//2.0 아이온", "10 스킨", "2025 챔피언스", "ABC", "rgx 2", "RGX 11z", "가이아", "넵튠", "프라임"])


class TierEmojiNameTest(unittest.TestCase):
    def test_name(self):
        from bot.services.tier_emoji import emoji_name

        n = emoji_name("https://media.valorant-api.com/contenttiers/411e4a55-4e59-7757-41f0-86a53f101bb5/displayicon.png")
        self.assertEqual(n, "tier_411e4a55")


class PickFansTest(unittest.TestCase):
    def test_pick_fans(self):
        from bot.services.odds_model import pick_fans

        rows = [(1, "Gen.G"), (2, "t1"), (3, None), (4, "Paper Rex"), (1, "Gen.G"), (5, "GEN G")]
        self.assertEqual(pick_fans(rows, "Gen.G", "T1"), [1, 2, 5])          # 대소문자·기호 무시, 중복 제거
        self.assertEqual(pick_fans(rows, "Gen.G", "T1", limit=2), [1, 2])
        self.assertEqual(pick_fans(rows, "TBD", ""), [])


class StockExtrasTest(unittest.TestCase):
    def test_find_surges(self):
        from bot.services import stock_model as sm

        a, b, c = (d.symbol for d in sm.STOCKS[:3])
        out = sm.find_surges({a: 1000, b: 1000, c: 1000, "ZZZ": 10}, {a: 1070, b: 930, c: 1030, "ZZZ": 100, "NEW": 5})
        self.assertEqual([(s, round(p)) for s, _, _, p in out], [(a, 7), (b, -7)])    # 6% 미만·모르는 종목·이전가 없음은 제외

    def test_parse_trade_ref(self):
        from bot.services.stock_model import parse_trade_ref

        self.assertEqual(parse_trade_ref("GENx10@1020"), ("GEN", 10, 1020))
        self.assertIsNone(parse_trade_ref("prediction:12"))
        self.assertIsNone(parse_trade_ref(None))

    def test_rainbow_frame_renders_continuous(self):
        from bot.render.profile_card import render_profile_card

        png = render_profile_card(dict(name="a", title="x", vp=1, rank=1, pred_win=0, pred_total=0, fav_team=None, fav_agent=None,
                                       theme="theme_default", frame="frame_rainbow"))
        self.assertTrue(png.startswith(b"\x89PNG"))


class MinesweeperTest(unittest.TestCase):
    def test_first_click_safe_and_flood_fill(self):
        import random
        from bot.services import minesweeper as ms
        for seed in range(50):
            b = ms.Board(4, 5, 4, random.Random(seed))
            b.reveal(0, 0)
            self.assertFalse(b.lost)
            self.assertNotIn((0, 0), b.mine)
            self.assertEqual(len(b.mine), 4)
            self.assertEqual(b.count(0, 0), 0)          # 주변도 비워 둬서 첫 칸은 빈 칸 → 넓게 열림
            self.assertGreater(len(b.opened), 1)

    def test_win_lose_and_flags(self):
        import random
        from bot.services import minesweeper as ms
        b = ms.Board(4, 5, 3, random.Random(1))
        b.reveal(1, 2)
        for p in list(b.cells()):
            if p not in b.mine:
                b.reveal(*p)
        self.assertTrue(b.won)
        b = ms.Board(4, 5, 3, random.Random(2))
        b.reveal(0, 0)
        m = next(iter(b.mine))
        b.toggle_flag(*m)
        b.reveal(*m)                                   # 깃발 꽂힌 칸은 안 열림
        self.assertFalse(b.lost)
        b.toggle_flag(*m)
        b.reveal(*m)
        self.assertTrue(b.lost and b.over)

    def test_spoiler_board(self):
        import random
        from bot.services import minesweeper as ms
        text = ms.spoiler_board(9, 9, 12, random.Random(3))
        self.assertEqual(len(text.splitlines()), 9)
        self.assertEqual(text.count("💣"), 12)
        self.assertEqual(text.count("||") // 2, 80)      # 한 칸만 열어 둠
        self.assertLess(len(text), 2000)                 # 메시지 길이 한도
        self.assertLess(len(ms.spoiler_board(10, 10, 18)), 2000)
