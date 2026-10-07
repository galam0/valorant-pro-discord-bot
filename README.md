# VALORANT Pro Discord Bot

VALORANT 프로팀·프로 선수 정보를 Discord Slash Command로 조회하는 봇입니다.
데이터는 [VLR.gg](https://www.vlr.gg)와 [ProSettings.net](https://prosettings.net)의 공개 정보를 수집해 PostgreSQL에 저장한 뒤 제공합니다.

> 현재 상태: **Phase 1** — `/ping` 동작, `/팀` · `/선수` 명령어 등록(준비 중 안내)

## 주요 기능 (로드맵)

| 명령어 | 설명 | 상태 |
|---|---|---|
| `/ping` | 봇 응답 속도 확인 | ✅ |
| `/팀 <이름>` | 팀 로고·로스터·코치진·최근 경기·대회 | 🚧 Phase 3 |
| `/선수 <닉네임>` | 선수 사진·감도·DPI·eDPI·장비·크로스헤어 | 🚧 Phase 4 |
| `/경기 [팀]` | 오늘/예정 경기, 팀별 최근·예정 경기 | 🚧 |
| `/랭킹` | 팀 랭킹 | 🚧 |
| `/관리 ...` | 데이터 갱신·상태 확인 (관리자 전용) | 🚧 |

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
| `DEV_GUILD_ID` | | 개발 서버 ID. 설정 시 명령어가 즉시 반영됨 |
| `ADMIN_USER_IDS` | | 관리자 사용자 ID (쉼표 구분) |
| `LOG_LEVEL` | | 기본 `INFO` |
| `PORT` | | Render가 자동 주입. 있으면 `/health` 서버를 띄움 (로컬에선 비워둠) |

`.env`는 `.gitignore`에 포함되어 있습니다. **토큰·DB 비밀번호를 절대 커밋하지 마세요.**

## PostgreSQL 설정 (Neon, 무료·만료 없음)

Render 무료 PostgreSQL은 30일 뒤 만료되므로 [Neon](https://neon.com) 무료 플랜을 사용합니다.

1. Neon 가입 → New Project (리전: AWS Asia Pacific (Singapore))
2. Dashboard → **Connect** → 연결 문자열 복사 (`postgresql://...?sslmode=require`)
3. Render 환경변수 `DATABASE_URL`에 붙여넣기

> 무료 플랜은 월 100 CU-hours이며 5분간 쿼리가 없으면 자동 일시정지됩니다. 스크래퍼 주기는 이 한도에 맞춰 설계합니다. (Phase 2·6에서 적용)

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

## 데이터 출처

- [VLR.gg](https://www.vlr.gg) — 팀, 로스터, 경기, 대회
- [ProSettings.net](https://prosettings.net) — 선수 설정, 장비, 크로스헤어

각 사이트의 robots.txt와 이용약관을 준수하며, 요청 간격을 두고 낮은 빈도로만 수집합니다.
이 프로젝트는 Riot Games, VLR.gg, ProSettings.net과 관련이 없습니다.
