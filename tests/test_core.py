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
from bot.scrapers.vlr import ParseError, parse_event_bracket, parse_player_page, parse_rankings, parse_search_events
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


if __name__ == "__main__":
    unittest.main()
