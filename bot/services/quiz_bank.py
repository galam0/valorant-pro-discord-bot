"""VALORANT 퀴즈 문제 은행. (질문, 정답, [오답 3개]) — 정답/오답은 출제할 때 섞는다."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

WEEKLY_LIMIT = 5      # 주(월요일 시작, 한국 시간)당 도전 횟수
REWARD = 60           # 정답 보상 VP
TIME_LIMIT = 30       # 답 고르는 시간(초)


def _role(agent: str, role: str) -> tuple[str, str, list[str]]:
    others = [r for r in ["타격대", "감시자", "전략가", "척후대"] if r != role]
    return (f"{agent}의 역할군은?", role, others)


QUESTIONS: list[tuple[str, str, list[str]]] = [
    _role("제트", "타격대"), _role("레이즈", "타격대"), _role("레이나", "타격대"), _role("네온", "타격대"),
    _role("세이지", "감시자"), _role("킬조이", "감시자"), _role("사이퍼", "감시자"), _role("체임버", "감시자"),
    _role("오멘", "전략가"), _role("바이퍼", "전략가"), _role("아스트라", "전략가"), _role("브림스톤", "전략가"),
    _role("소바", "척후대"), _role("스카이", "척후대"), _role("페이드", "척후대"), _role("브리치", "척후대"),
    ("한 경기에서 먼저 몇 라운드를 이기면 승리(정규 라운드 기준)일까?", "13라운드", ["10라운드", "12라운드", "15라운드"]),
    ("전반전은 몇 라운드 후 공수가 바뀔까?", "12라운드", ["10라운드", "13라운드", "15라운드"]),
    ("한 팀은 몇 명으로 구성될까?", "5명", ["4명", "6명", "7명"]),
    ("스파이크를 설치한 뒤 폭발까지 걸리는 시간은?", "45초", ["30초", "60초", "90초"]),
    ("오퍼레이터의 가격은?", "4,700 크레딧", ["3,700 크레딧", "4,000 크레딧", "5,200 크레딧"]),
    ("밴달의 가격은?", "2,900 크레딧", ["2,400 크레딧", "3,200 크레딧", "1,600 크레딧"]),
    ("기본 권총 클래식의 가격은?", "무료", ["200 크레딧", "400 크레딧", "800 크레딧"]),
    ("셰리프의 가격은?", "800 크레딧", ["500 크레딧", "1,100 크레딧", "1,600 크레딧"]),
    ("세이지의 궁극기는?", "부활", ["치유 구슬", "방벽 구슬", "감속 구슬"]),
    ("소바의 궁극기는?", "사냥꾼의 분노", ["궤도 타격", "블레이드 스톰", "런 잇 백"]),
    ("제트의 궁극기는?", "블레이드 스톰", ["쇼스토퍼", "엠프리스", "오버드라이브"]),
    ("브림스톤의 궁극기는?", "궤도 타격", ["프롬 더 섀도우", "토실", "블레이즈"]),
    ("다음 중 스파이크 설치 사이트가 3개인 맵은?", "헤이븐", ["어센트", "바인드", "스플릿"]),
    ("텔레포터가 있는 맵은?", "바인드", ["아이스박스", "브리즈", "어센트"]),
    ("랭크 티어 중 가장 높은 것은?", "래디언트", ["이모탈", "어센던트", "다이아몬드"]),
    ("랭크 티어 순서에서 플래티넘 바로 위 티어는?", "다이아몬드", ["골드", "어센던트", "이모탈"]),
    ("VALORANT 정식 출시일은?", "2020년 6월 2일", ["2019년 12월 1일", "2020년 4월 7일", "2021년 1월 1일"]),
    ("VALORANT를 개발한 회사는?", "라이엇 게임즈", ["밸브", "에픽게임즈", "블리자드"]),
    ("VCT Champions 2021 베를린 우승팀은?", "Acend", ["Gambit", "Sentinels", "Fnatic"]),
    ("VCT Champions 2022 이스탄불 우승팀은?", "LOUD", ["OpTic Gaming", "Paper Rex", "DRX"]),
    ("VCT Champions 2023 로스앤젤레스 우승팀은?", "Evil Geniuses", ["Paper Rex", "Fnatic", "LOUD"]),
    ("VCT Champions 2024 서울 우승팀은?", "EDward Gaming", ["Team Heretics", "Gen.G", "Sentinels"]),
]


def pick_question(rng: random.Random | None = None, exclude: set[int] | None = None) -> tuple[int, str, list[str], int]:
    """(문제 번호, 질문, 보기 4개, 정답 위치)."""
    r = rng or random
    pool = [i for i in range(len(QUESTIONS)) if not exclude or i not in exclude] or list(range(len(QUESTIONS)))
    idx = r.choice(pool)
    q, answer, wrong = QUESTIONS[idx]
    options = [answer] + list(wrong)
    r.shuffle(options)
    return idx, q, options, options.index(answer)


def week_start(now: datetime) -> datetime:
    """이번 주 월요일 00:00 (now의 시간대 기준)."""
    d = now - timedelta(days=now.weekday())
    return d.replace(hour=0, minute=0, second=0, microsecond=0)
