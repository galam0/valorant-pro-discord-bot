"""영어 원본 데이터 → 한국어 표시 변환.

고유명사(팀명, 선수 닉네임, 실명)는 번역하지 않는다. 여기서는 역할, 상태, 대회 단계, 국가만 다룬다.
사전에 없는 값은 원문을 그대로 돌려준다 (잘못 번역하는 것보다 낫다).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 로스터 역할 (DB에 저장되는 내부 코드 → 한국어)
# ---------------------------------------------------------------------------

ROLE_KO: dict[str, str] = {
    "player": "선수",
    "substitute": "후보 선수",
    "inactive": "비활성",
    "head_coach": "감독",
    "coach": "코치",
    "assistant_coach": "코치",
    "analyst": "분석관",
    "manager": "매니저",
    "performance_coach": "퍼포먼스 코치",
    "staff": "스태프",
}

# VLR 로스터 태그(소문자) → 내부 코드
VLR_ROLE_TAG: dict[str, str] = {
    "sub": "substitute",
    "substitute": "substitute",
    "inactive": "inactive",
    "head coach": "head_coach",
    "coach": "coach",
    "assistant coach": "assistant_coach",
    "analyst": "analyst",
    "manager": "manager",
    "performance coach": "performance_coach",
}

STAFF_ROLES = {"head_coach", "coach", "assistant_coach", "analyst", "manager", "performance_coach", "staff"}


def role_ko(role: str) -> str:
    return ROLE_KO.get(role, role)


# ---------------------------------------------------------------------------
# 경기 상태 / 결과
# ---------------------------------------------------------------------------

MATCH_STATUS_KO: dict[str, str] = {
    "upcoming": "예정",
    "live": "진행 중",
    "completed": "종료",
}


def match_status_ko(status: str) -> str:
    return MATCH_STATUS_KO.get(status, status)


# ---------------------------------------------------------------------------
# 대회 단계 (Playoffs–Upper Quarterfinals 같은 문자열)
# ---------------------------------------------------------------------------

# 긴 표현부터 바꾸도록 길이 내림차순으로 적용
_STAGE_TERMS: dict[str, str] = {
    "Upper Quarterfinals": "승자조 8강",
    "Upper Semifinals": "승자조 4강",
    "Upper Final": "승자조 결승",
    "Upper Round 1": "승자조 1라운드",
    "Lower Round 1": "패자조 1라운드",
    "Lower Round 2": "패자조 2라운드",
    "Lower Round 3": "패자조 3라운드",
    "Lower Quarterfinals": "패자조 8강",
    "Lower Semifinals": "패자조 4강",
    "Lower Final": "패자조 결승",
    "Grand Final": "결승전",
    "Quarterfinals": "8강",
    "Semifinals": "4강",
    "Third Place": "3·4위전",
    "Round of 32": "32강",
    "Round of 16": "16강",
    "Play-In": "플레이인",
    "Final": "결승",
    "Playoffs": "플레이오프",
    "Group Stage": "그룹 스테이지",
    "Swiss Stage": "스위스 스테이지",
    "Regular Season": "정규 시즌",
    "Opening": "오프닝",
    "Elimination": "탈락전",
    "Decider": "최종전",
    "Winners": "승자전",
    "Main Event": "본선",
    "Qualifier": "예선",
    "Showmatch": "쇼매치",
    "Group": "그룹",
    "Week": "주차",
    "Round": "라운드",
    "UBQF": "승자조 8강",
    "UBSF": "승자조 4강",
    "UBF": "승자조 결승",
    "LBQF": "패자조 8강",
    "LBSF": "패자조 4강",
    "LBF": "패자조 결승",
    "GF": "결승전",
}
_STAGE_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(k)}\b" for k in sorted(_STAGE_TERMS, key=len, reverse=True))
)


def stage_ko(text: str | None) -> str | None:
    """'Playoffs–Upper Quarterfinals' → '플레이오프 · 승자조 8강'."""
    if not text:
        return text
    # 'Week 3' → '3주차', 'Round 2' → '2라운드' (숫자가 앞에 오는 한국어 어순)
    out = re.sub(r"\bWeek\s+(\d+)", r"\1주차", text)
    out = re.sub(r"(?<!Upper )(?<!Lower )\bRound\s+(\d+)", r"\1라운드", out)
    out = _STAGE_PATTERN.sub(lambda m: _STAGE_TERMS[m.group(0)], out)
    out = re.sub(r"\s*[–—:⋅]\s*", " · ", out)  # 구분자 통일
    return re.sub(r"\s+", " ", out).strip(" ·")


# ---------------------------------------------------------------------------
# 국가
# ---------------------------------------------------------------------------

COUNTRY_KO: dict[str, str] = {
    "kr": "대한민국", "jp": "일본", "cn": "중국", "tw": "대만", "hk": "홍콩", "sg": "싱가포르",
    "my": "말레이시아", "id": "인도네시아", "ph": "필리핀", "th": "태국", "vn": "베트남", "in": "인도",
    "au": "호주", "nz": "뉴질랜드", "us": "미국", "ca": "캐나다", "mx": "멕시코", "br": "브라질",
    "ar": "아르헨티나", "cl": "칠레", "co": "콜롬비아", "pe": "페루", "gb": "영국", "uk": "영국",
    "fr": "프랑스", "de": "독일", "es": "스페인", "it": "이탈리아", "pt": "포르투갈", "nl": "네덜란드",
    "be": "벨기에", "se": "스웨덴", "no": "노르웨이", "dk": "덴마크", "fi": "핀란드", "pl": "폴란드",
    "cz": "체코", "at": "오스트리아", "ch": "스위스", "ru": "러시아", "ua": "우크라이나", "by": "벨라루스",
    "tr": "튀르키예", "sa": "사우디아라비아", "ae": "아랍에미리트", "eg": "이집트", "ma": "모로코",
    "il": "이스라엘", "lt": "리투아니아", "lv": "라트비아", "ee": "에스토니아", "rs": "세르비아",
    "hr": "크로아티아", "ro": "루마니아", "bg": "불가리아", "gr": "그리스", "hu": "헝가리", "ie": "아일랜드",
    "kz": "카자흐스탄", "mn": "몽골", "pk": "파키스탄", "kh": "캄보디아", "mo": "마카오",
    "eu": "유럽", "un": "국제",
}


def country_ko(code: str | None, fallback: str | None = None) -> str | None:
    if not code:
        return fallback
    return COUNTRY_KO.get(code.lower(), fallback or code.upper())


def flag_emoji(code: str | None) -> str:
    """'kr' → 🇰🇷. 두 글자 국가 코드가 아니면 🌐."""
    if not code:
        return "🌐"
    code = code.lower()
    if code == "uk":
        code = "gb"
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord("a")) for c in code)
