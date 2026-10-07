"""외부 서비스 없이 돌아가는 핵심 로직 테스트.  실행: python -m unittest discover -s tests -v"""

import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from tests import _stubs  # noqa: F401  (다른 import보다 먼저)

from bot.render.compare_card import render_compare_card
from bot.render.player_card import render_player_card
from bot.render.ranking_card import render_ranking_card
from bot.render.bracket_card import render_bracket_card
from bot.scrapers.vlr import ParseError, parse_event_bracket, parse_rankings, parse_search_events
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


if __name__ == "__main__":
    unittest.main()
