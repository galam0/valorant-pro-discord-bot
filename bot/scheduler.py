"""자동 갱신 스케줄러 (APScheduler).

Neon 무료 플랜(월 100 CU-hours, 5분 쿼리가 없으면 일시정지)과 VLR.gg 부하를 고려한 주기:

| 작업        | 주기                | 내용 |
|-------------|---------------------|------|
| matches     | 1시간               | 예정·진행 경기 + 최근 결과 → DB (요청 2회) |
| live        | 10분                | /matches 에서 진행 중 경기 확인(요청 1회, DB 안 씀). 진행 중이면 상세 기록을 DB에 저장.
|             |                     | 방금 끝난 경기는 최종 기록을 한 번 더 저장 |
| teams       | 2달에 한 번 (1·3·5·7·9·11월 1일 04:30 한국) | 저장된 모든 팀의 로스터·경기. 중간에는 /관리 팀갱신·전체팀갱신으로 직접 |

- 진행 중인 경기가 없으면 live 작업은 DB를 건드리지 않아 Neon이 잠들 수 있다.
- 작업이 겹치지 않게 max_instances=1, 실패해도 다음 주기에 다시 시도하고 봇은 계속 동작한다.
- SCHEDULER_ENABLED=0 으로 끌 수 있다.
"""

from __future__ import annotations

import logging
import os

from bot.database.database import db
from bot.scrapers.vlr import vlr
from bot.services import match_service, prediction_service, team_service

log = logging.getLogger("valobot.scheduler")

MAX_LIVE_DETAILS = 6          # 한 번에 상세를 저장할 진행 중 경기 수 (요청 간격 2초 × 6 = 12초)
_live_ids: set[int] = set()   # 직전 확인 때 진행 중이던 경기 (끝났는지 알아내기 위해)

try:  # 패키지가 없어도 봇은 떠야 한다
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:  # pragma: no cover
    AsyncIOScheduler = None  # type: ignore[assignment,misc]
    CronTrigger = None  # type: ignore[assignment,misc]

_scheduler: "AsyncIOScheduler | None" = None


def enabled() -> bool:
    return os.getenv("SCHEDULER_ENABLED", "1").strip().lower() not in {"0", "false", "no"}


# ---------------------------------------------------------------------------
# 작업
# ---------------------------------------------------------------------------


async def job_matches() -> None:
    try:
        count = await match_service.refresh_matches(include_results=True)
        log.info("[자동] 경기 목록 갱신: %d개", count)
        await _settle_sweep()
    except Exception as exc:
        log.warning("[자동] 경기 목록 갱신 실패: %s: %s", type(exc).__name__, exc)


async def _settle_sweep() -> None:
    """열린 예측이 남은 끝난 경기를 정산 (놓친 경기 보완). 경기 목록 갱신 직후라 DB는 이미 깨어 있다."""
    try:
        await prediction_service.settle_finished()
    except Exception as exc:
        log.warning("[자동] 예측 정산 실패: %s: %s", type(exc).__name__, exc)


async def job_live() -> None:
    """진행 중 경기 확인. 진행 중이 없으면 DB를 쓰지 않는다."""
    global _live_ids
    try:
        items = await vlr.fetch_upcoming_matches()
    except Exception as exc:
        log.warning("[자동] 진행 중 경기 확인 실패: %s: %s", type(exc).__name__, exc)
        return

    live = [i.vlr_id for i in items if i.status == "live"]
    just_ended = sorted(_live_ids - set(live))
    todo = live[:MAX_LIVE_DETAILS] + just_ended[:MAX_LIVE_DETAILS]
    _live_ids = set(live)
    if not todo:
        return

    saved = 0
    for vlr_id in todo:
        try:
            await match_service.get_match_detail(vlr_id, force=True)
            saved += 1
        except Exception as exc:
            log.warning("[자동] 경기 상세 저장 실패 (%s): %s: %s", vlr_id, type(exc).__name__, exc)
    log.info("[자동] 진행 중 %d경기 · 방금 종료 %d경기 → 상세 %d건 저장", len(live), len(just_ended), saved)
    for vlr_id in just_ended[:MAX_LIVE_DETAILS]:     # 방금 끝난 경기는 바로 예측 정산 (DB는 이미 깨어 있음)
        try:
            await prediction_service.settle_match(vlr_id)
        except Exception as exc:
            log.warning("[자동] 예측 정산 실패 (%s): %s: %s", vlr_id, type(exc).__name__, exc)


async def job_teams() -> None:
    if team_service.bulk_refresh_running():
        log.info("[자동] 수동 전체 갱신이 진행 중이라 팀 갱신을 건너뜁니다.")
        return
    try:
        queries = await team_service.saved_team_queries()
        if not queries:
            return
        result = await team_service.refresh_many(queries)
        log.info("[자동] 팀 갱신 완료: 성공 %d · 실패 %d", len(result.ok), len(result.failed))
    except Exception as exc:
        log.warning("[자동] 팀 갱신 실패: %s: %s", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# 시작 / 종료
# ---------------------------------------------------------------------------


def start() -> None:
    global _scheduler
    if not enabled():
        log.info("자동 갱신이 꺼져 있습니다 (SCHEDULER_ENABLED=0).")
        return
    if AsyncIOScheduler is None:
        log.warning("APScheduler 가 설치되어 있지 않아 자동 갱신을 건너뜁니다. (requirements.txt 확인)")
        return
    if not db.configured:
        log.info("DB가 설정되지 않아 자동 갱신을 건너뜁니다.")
        return

    sched = AsyncIOScheduler(timezone="Asia/Seoul")
    common = dict(max_instances=1, coalesce=True, misfire_grace_time=120)
    # 시작 직후 한꺼번에 몰리지 않게 약간씩 늦춰서 첫 실행
    sched.add_job(job_matches, "interval", minutes=60, id="matches", jitter=20,
                  next_run_time=_in(seconds=90), **common)
    sched.add_job(job_live, "interval", minutes=10, id="live", jitter=10,
                  next_run_time=_in(seconds=150), **common)
    # 재배포·재시작으로 그 시각을 놓쳐도 6시간 안에 켜지면 실행
    sched.add_job(job_teams, CronTrigger(month="1,3,5,7,9,11", day=1, hour=4, minute=30, timezone="Asia/Seoul"),
                  id="teams", **{**common, "misfire_grace_time": 6 * 3600})
    sched.start()
    _scheduler = sched
    log.info("자동 갱신 시작: 경기 1시간 · 진행 중 10분 · 팀 2달에 한 번")


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_runs() -> dict[str, str]:
    """/관리 상태 에 보여줄 다음 실행 시각."""
    if _scheduler is None:
        return {}
    out = {}
    for job in _scheduler.get_jobs():
        if job.next_run_time:
            out[job.id] = job.next_run_time.strftime("%m/%d %H:%M")
    return out


def _in(seconds: int):
    from datetime import datetime, timedelta

    return datetime.now().astimezone() + timedelta(seconds=seconds)
