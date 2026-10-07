# VALORANT Pro Discord Bot

VALORANT 프로팀·프로 선수 정보를 Discord Slash Command로 조회하는 봇입니다.
데이터는 [VLR.gg](https://www.vlr.gg)와 [ProSettings.net](https://prosettings.net)의 공개 정보를 수집해 PostgreSQL에 저장한 뒤 제공합니다.

> 현재 상태: 팀·경기·전적·랭킹·비교 + 자동 갱신 동작 중. `/선수`는 ProSettings 허가 전까지 준비 중(관리자만 사용)

## 주요 기능 (로드맵)

| 명령어 | 설명 | 상태 |
|---|---|---|
| `/ping` | 봇·DB 응답 속도 확인 | ✅ |
| `/팀 <이름>` | 팀 로고·로스터·코치진·최근 경기·대회 (한국어 별칭 검색) | ✅ 기본 |
| `/선수 <닉네임>` | 선수 사진·감도·DPI·eDPI·장비·크로스헤어 미리보기 (오타 보정: texture → t3xture) | ✅ |
| `/경기 [팀]` | 진행 중·예정 경기, 팀별 최근·예정 경기 (메뉴로 경기 상세 열기) | ✅ |
| `/전적 <팀>` | 진행 중 또는 최근 경기의 맵별 점수·선수 K/D/A·ACS·ADR·HS% | ✅ |
| `/랭킹 [지역]` | VLR.gg 팀 랭킹 (세계·한국·유럽 등 13개 지역, 1시간 캐시) | ✅ |
| `/비교 <팀1> <팀2>` | 두 팀의 최근 5경기·로스터·맞대결 비교 (이미지 카드, 저장된 경기 기준) | ✅ |
| `/관리 별칭추가 <팀> <별칭>` · `별칭삭제` · `별칭목록` | 팀 검색 별칭 관리 (예: 젠지 → Gen.G) (관리자) | ✅ |
| `/관리 팀갱신 <팀>` | VLR.gg에서 팀 정보 다시 수집 (관리자) | ✅ |
| `/관리 전체팀갱신 <대상>` | 저장된 팀 전체 또는 주요 리그(VCT) 팀 전체를 한 번에 수집 (관리자, 몇 분 소요) | ✅ |
| `/관리 선수갱신 <닉네임>` | ProSettings에서 선수 설정 다시 수집 (관리자) | ✅ |
| `/관리 선수설정등록 <닉네임> ...` | 선수 DPI·감도·장비·크로스헤어 코드를 직접 입력 (ProSettings 차단 시 대안, 관리자) | ✅ |
| `/관리 경기갱신` | 진행 중·예정 경기와 최근 결과 수집 (관리자) | ✅ |
| `/관리 상태` | 봇·DB·수집 기록 확인 (관리자) | ✅ |

## 아키텍처

```
VLR.gg / ProSettings.net → Scraper(주기 실행) → PostgreSQL → Discord Bot
```

Discord 명령어는 외부 사이트에 직접 요청하지 않고 항상 DB에서만 읽습니다.

## 요구 사항

- Python 3.12
- Discord Bot 계정
- PostgreSQL (Phase 2부터)

## 설치 및 로컬 실행

```bash
git clone <your-repo-url>
cd valorant-pro-discord-bot

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
# .env 에 DISCORD_TOKEN 입력

python -m bot.main
```

## Discord Bot 만들기

1. https://discord.com/developers/applications → **New Application**
2. 왼쪽 **Bot** 메뉴 → **Reset Token** → 토큰 복사 → `.env`의 `DISCORD_TOKEN`에 붙여넣기
3. Privileged Gateway Intents는 **모두 꺼둬도 됩니다** (Slash Command만 사용)
4. **OAuth2 → URL Generator**
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`
5. 생성된 URL로 봇을 서버에 초대

## 환경변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | 봇 토큰 |
| `DATABASE_URL` | Phase 2~ | PostgreSQL 연결 문자열 |
| `ADMIN_USER_IDS` | | 관리자 사용자 ID (쉼표 구분) |
| `LOG_LEVEL` | | 기본 `INFO` |
| `WORKER_TOKEN` | | PC 수집기와 공유하는 비밀값 (ProSettings 허가 후 사용) |
| `SCHEDULER_ENABLED` | | 자동 갱신 사용 (기본 `1`) |
| `PLAYER_COMMAND_ENABLED` | | `/선수` 공개 여부 (기본 `0` = 관리자만) |
| `PORT` | | Render가 자동 주입. 있으면 `/health` 서버를 띄움 (로컬에선 비워둠) |

`.env`는 `.gitignore`에 포함되어 있습니다. **토큰·DB 비밀번호를 절대 커밋하지 마세요.**

## PostgreSQL 설정 (Neon, 무료·만료 없음)

Render 무료 PostgreSQL은 30일 뒤 만료되므로 [Neon](https://neon.com) 무료 플랜을 사용합니다.

1. Neon 가입 → New Project (리전: AWS Asia Pacific (Singapore))
2. Dashboard → **Connect** → 연결 문자열 복사 (`postgresql://...?sslmode=require`)
3. Render 환경변수 `DATABASE_URL`에 붙여넣기

> 무료 플랜은 월 100 CU-hours이며 5분간 쿼리가 없으면 자동 일시정지됩니다. 스크래퍼 주기는 이 한도에 맞춰 설계합니다. (Phase 6)
> 이 때문에 `/health`는 DB에 쿼리하지 않습니다. (UptimeRobot이 5분마다 DB를 깨우면 한도를 넘음)

### 스키마 관리 (Alembic)

- 봇이 시작할 때 `alembic upgrade head`를 자동으로 적용합니다. (`AUTO_MIGRATE=0`으로 끌 수 있음)
- 모델(`bot/database/models.py`)을 바꾼 뒤에는 마이그레이션 파일을 만들어 커밋합니다.

```bash
alembic revision --autogenerate -m "변경 내용"   # migrations/versions/ 에 파일 생성
alembic upgrade head                            # 로컬 DB에 적용
```

| 테이블 | 내용 |
|---|---|
| `teams` / `team_aliases` | 팀, 검색 별칭 (젠지 → GEN.G) |
| `players` / `team_members` | 선수, 팀 로스터·코치진 |
| `tournaments` / `matches` | 대회, 경기 |
| `player_settings` / `equipment` / `crosshairs` | 감도·DPI, 장비, 크로스헤어 |
| `scrape_runs` | 데이터 수집 실행 기록 |

## Render 배포 (무료 Web Service)

1. 이 저장소를 GitHub에 push
2. [Render](https://dashboard.render.com) → **New → Blueprint** → 저장소 선택 → `render.yaml` 자동 인식
3. 환경변수 입력: `DISCORD_TOKEN` (필수), `DEV_GUILD_ID` (선택)
4. **Apply** → 배포 로그에 `로그인: 봇이름#...`이 뜨면 성공
5. 서비스 URL(`https://<이름>.onrender.com/health`)이 `{"status": "ok", ...}`를 반환하는지 확인

### 24시간 깨워두기

Render 무료 Web Service는 외부 요청이 15분 없으면 잠듭니다. 무료 모니터링 서비스로 주기적으로 깨워둡니다.

1. [UptimeRobot](https://uptimerobot.com) 가입 → **New Monitor**
2. Type: HTTP(s), URL: `https://<이름>.onrender.com/health`, Interval: **5분**

워크스페이스당 무료 시간은 월 750시간이라 서비스 1개를 한 달 내내 켜둘 수 있습니다. (무료 서비스를 2개 이상 돌리면 부족)

`main` 브랜치에 push하면 자동으로 재배포됩니다.

### 로그인이 `Cloudflare IP 차단(1015)`으로 계속 실패할 때

Render 무료 서버는 리전별로 IP를 여러 서비스가 공유하므로, 다른 봇 때문에 Discord가 그 IP를 일시 차단할 수 있습니다.
봇은 죽지 않고 최대 30분 간격으로 자동 재시도하지만, 오래 지속되면 다른 리전에 서비스를 새로 만듭니다.
(리전은 생성 후 바꿀 수 없으므로 `render.yaml`의 `name`과 `region`을 함께 바꾸고 Blueprint를 다시 동기화)

## 데이터 수집 방식 (VLR.gg)

- 공개 API가 없어 HTML을 파싱합니다. 선택자와 확인한 페이지 구조는 `bot/scrapers/vlr.py` 상단에 정리되어 있습니다.
- 요청 규칙(`bot/scrapers/http.py`): 봇 User-Agent, 같은 사이트 요청 간 최소 2초, 타임아웃 20초, 429/5xx 재시도(지수 백오프), robots.txt 확인.
- VLR 목록 페이지의 시각은 서버 위치 시간대로 표시되므로, 경기 상세 페이지 1개로 시간대를 보정해 UTC로 저장합니다.
  Discord에는 `<t:...>` 타임스탬프로 보내서 보는 사람의 시간대로 표시됩니다.
- 경기 상세(맵별 기록)는 `matches.detail`(JSONB)에 캐시합니다. 진행 중 경기는 1분, 예정 경기는 10분 동안 캐시를 쓰고,
  종료된 경기는 한 번 가져오면 다시 요청하지 않습니다. 같은 경기를 여러 명이 동시에 열어도 VLR 요청은 1번입니다.
- 관리자는 `ADMIN_USER_IDS` 또는 서버 관리자 권한으로 판단합니다.

## 데이터 수집 방식 (ProSettings.net)

- robots.txt에서 검색(`/?s=`, `/search/`)과 API(`/wp-json/`)가 금지되어 있어 사용하지 않고, 허용된 선수 페이지(`/players/{닉네임}/`)만 읽습니다.
- 선수 설정은 12시간 캐시합니다. `/선수` 요청 시 저장된 설정이 없거나 12시간이 지났을 때만 가져옵니다.
- 닉네임 검색은 DB에 저장된 선수(VLR 로스터) 기준으로 오타를 보정한 뒤 해당 선수 페이지를 찾습니다.

## PC 수집기 (ProSettings)

ProSettings는 Render 같은 데이터센터 IP의 요청을 차단합니다(robots.txt부터 403).
그래서 ProSettings 페이지 요청만 **내 PC에서 실행하는 수집기**가 대신 가져와 봇에게 넘겨줍니다.

```
/선수 stax → 봇이 작업 대기 → PC 수집기가 /worker/next 로 받아감 → ProSettings 요청 → HTML을 봇에 전달 → 봇이 DB 저장 후 카드 표시
```

- PC에는 DB 비밀번호·Discord 토큰이 필요 없습니다. `BOT_URL`, `WORKER_TOKEN`만 설정합니다.
- PC가 꺼져 있으면 봇은 마지막으로 저장된 설정을 보여주고 "수집 PC가 꺼져 있음"을 안내합니다.
- 수집기도 robots.txt와 2초 요청 간격을 지키며, prosettings.net 주소만 처리합니다.

### 설정 방법 (윈도우)

1. 무작위 토큰 만들기 (PowerShell): `[guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")`
2. Render 환경변수 `WORKER_TOKEN`에 그 값을 넣고 저장 (자동 재배포)
3. PC에 저장소를 받고 `.env`에 `WORKER_TOKEN`(같은 값)과 `BOT_URL`(Render 주소) 입력
4. `run_worker.bat` 더블클릭 → "봇과 연결됨"이 뜨면 완료
5. `/관리 상태`에서 "PC 수집기 🟢 켜짐" 확인

## 자동 갱신 (APScheduler)

봇이 켜져 있는 동안 `bot/scheduler.py`가 데이터를 알아서 갱신합니다. (`SCHEDULER_ENABLED=0`으로 끔)

| 작업 | 주기 | 내용 |
|---|---|---|
| 경기 목록 | 1시간 | 예정·진행 경기와 최근 결과 |
| 진행 중 경기 | 10분 | VLR에서 진행 중 경기를 확인하고, 있으면 맵별 점수·선수 기록 저장. 방금 끝난 경기는 최종 기록 저장 |
| 팀 정보 | 2달에 한 번 (홀수 달 1일 04:30 KST) | 저장된 모든 팀의 로스터·경기. 중간에는 `/관리 팀갱신`·`/관리 전체팀갱신`으로 직접 |

진행 중인 경기가 없으면 DB를 건드리지 않아서 Neon이 잠들 수 있습니다 (월 100 CU-hours 한도 절약).
`/관리 상태`에서 다음 실행 시각을 볼 수 있습니다.

## 테스트

외부 서비스 없이 도는 핵심 로직 테스트(파서·1군 필터·이미지 카드·자동 갱신 로직)가 있습니다.

```bash
python -m unittest discover -s tests -v
```

## 문제 해결

| 증상 | 확인 |
|---|---|
| 봇이 시작하자마자 죽음 | Render 로그의 `ExtensionFailed` 줄 — 명령어 정의 오류 (예: 옵션 범위 타입) |
| 로그인 `1015` / 429 반복 | Render IP 차단. 봇이 최대 30분 간격으로 자동 재시도, 오래가면 리전 변경 |
| 명령어가 안 보임 | 봇 초대 시 `applications.commands` 스코프 확인, 재배포 1~2분 대기 |
| `/랭킹`·`/팀` 데이터가 비어 있음 | `/관리 전체팀갱신 주요 리그 팀 전체` 실행 |
| 자동 갱신이 안 도는 것 같음 | `/관리 상태`의 "자동 갱신 (다음 실행)" 확인, `SCHEDULER_ENABLED` 확인 |
| Neon 사용량이 빠르게 늘어남 | 자동 갱신 주기 늘리기 (`bot/scheduler.py`) 또는 `SCHEDULER_ENABLED=0` |

## 데이터 출처

- [VLR.gg](https://www.vlr.gg) — 팀, 로스터, 경기, 대회
- [ProSettings.net](https://prosettings.net) — 선수 설정, 장비, 크로스헤어

각 사이트의 robots.txt와 이용약관을 준수하며, 요청 간격을 두고 낮은 빈도로만 수집합니다.
이 프로젝트는 Riot Games, VLR.gg, ProSettings.net과 관련이 없습니다.
