"""외부 서비스 없이 돌아가는 핵심 로직 테스트.  실행: python -m unittest discover -s tests -v"""

import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from tests import _stubs  # noqa: F401  (다른 import보다 먼저)

from bot.render.compare_card import render_compare_card
from bot.render.player_card import render_player_card
from bot.render.ranking_card import render_ranking_card
from bot.scrapers.vlr import ParseError, parse_rankings
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
