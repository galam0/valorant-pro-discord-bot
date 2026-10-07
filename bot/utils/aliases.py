"""팀 한국어 별칭.

키: VLR 공식 팀명을 normalize_key 한 값 (소문자, 영문·숫자·한글만)
값: 그 팀을 가리키는 한국어/약칭 목록

팀이 DB에 저장될 때 자동으로 team_aliases 에 등록된다.
여러 팀이 같은 별칭을 쓰면 먼저 등록된 팀만 갖는다 (엉뚱한 팀 매칭 방지).
새 별칭은 여기 추가하거나, 추후 /관리 별칭추가 명령어로 넣는다.
"""

from __future__ import annotations

# /관리 전체팀갱신 대상=주요 팀 에서 수집할 팀 (VLR 검색어). 리그 구성이 바뀌면 여기만 고치면 된다.
MAJOR_TEAMS: list[str] = [
    # Pacific
    "T1", "Gen.G", "DRX", "Nongshim RedForce", "Paper Rex", "Rex Regum Qeon", "Talon Esports",
    "Team Secret", "ZETA DIVISION", "DetonatioN FocusMe", "Global Esports", "BOOM Esports",
    # Americas
    "Sentinels", "NRG", "100 Thieves", "Cloud9", "Evil Geniuses", "G2 Esports", "LOUD", "FURIA",
    "MIBR", "Leviatán", "KRÜ Esports", "2Game Esports",
    # EMEA
    "FNATIC", "Team Heretics", "Team Liquid", "Team Vitality", "Karmine Corp", "Natus Vincere",
    "FUT Esports", "BBL Esports", "GIANTX", "KOI", "Gentle Mates", "Apeks",
    # China
    "EDward Gaming", "Bilibili Gaming", "Trace Esports", "FunPlus Phoenix", "JD Gaming",
    "Dragon Ranger Gaming", "All Gamers", "Titan Esports Club", "Wolves Esports", "Xi Lai Gaming",
    "TYLOO", "Nova Esports",
]

KO_TEAM_ALIASES: dict[str, list[str]] = {
    # Pacific
    "t1": ["티원", "티1"],
    "geng": ["젠지", "젠쥐", "gen.g", "genge"],
    "drx": ["디알엑스", "드럭스"],
    "nongshimredforce": ["농심", "농심레드포스", "ns", "nsrf"],
    "paperrex": ["페이퍼렉스", "페퍼렉스", "prx"],
    "rexregumqeon": ["렉스레굼퀀", "rrq"],
    "talonesports": ["탈론"],
    "teamsecret": ["팀시크릿"],
    "zetadivision": ["제타", "제타디비전"],
    "detonationfocusme": ["데토네이션", "dfm"],
    "globalesports": ["글로벌이스포츠"],
    "boomesports": ["붐이스포츠"],
    # Americas
    "sentinels": ["센티널즈", "센티넬즈", "센티넬", "sen"],
    "nrg": ["엔알지", "nrg esports"],
    "100thieves": ["100씨브즈", "백도둑", "100t"],
    "cloud9": ["클라우드나인", "c9"],
    "loud": ["라우드"],
    "furia": ["퓨리아"],
    "mibr": ["미브르"],
    "leviatan": ["레비아탄", "lev"],
    "kru": ["크루"],
    "kruesports": ["크루"],
    "evilgeniuses": ["이블지니어스", "eg"],
    "g2esports": ["지투", "g2", "지이치케이"],
    # EMEA
    "fnatic": ["프나틱", "fnc"],
    "teamheretics": ["헤레틱스", "팀헤레틱스", "th"],
    "teamliquid": ["리퀴드", "팀리퀴드", "tl"],
    "teamvitality": ["바이탈리티", "vit"],
    "karminecorp": ["카르민코프", "kc"],
    "natusvincere": ["나비", "navi"],
    "futesports": ["퍼트", "fut"],
    "bbl": ["비비엘"],
    "giantx": ["자이언트엑스", "gx"],
    "koi": ["코이"],
    "movistarkoi": ["코이"],
    # China
    "edwardgaming": ["에드워드게이밍", "edg"],
    "bilibiligaming": ["빌리빌리", "blg"],
    "traceesports": ["트레이스", "te"],
    "funplusphoenix": ["fpx", "펀플러스피닉스"],
    "jdgaming": ["징동", "jdg"],
    "dragonranger": ["드래곤레인저", "drg"],
    "allgamers": ["올게이머즈", "ag"],
    "titanesportsclub": ["타이탄", "tec"],
    "wolvesesports": ["울브스", "wol"],
    "xilaibravo": ["시라이브라보", "xlg"],
}
