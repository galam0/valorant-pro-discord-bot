"""DB 모델 (SQLAlchemy 2.0 Declarative).

설계 원칙
- 외부 사이트의 고유 ID(vlr_id, prosettings_slug)에 UNIQUE를 걸어 같은 데이터가 중복 저장되지 않게 한다.
  스크래퍼는 이 키로 upsert 한다.
- 원본 페이지 구조가 바뀌어도 정보를 잃지 않도록 일부 테이블은 `raw`(JSONB)에 원본 값을 함께 보관한다.
- 스키마 변경은 반드시 Alembic 마이그레이션으로 한다 (migrations/versions/).

테이블
  teams            팀 (VLR)
  team_aliases     팀 별칭 (젠지 → GEN.G)
  players          선수 (VLR + ProSettings)
  team_members     팀 로스터/스태프 (선수 레코드가 없는 코치도 이름으로 저장)
  tournaments      대회 (VLR)
  matches          경기 (VLR)
  player_settings  감도/DPI 등 (ProSettings)
  equipment        장비 (ProSettings)
  crosshairs       크로스헤어 (ProSettings)
  scrape_runs      수집 실행 기록 (/관리 상태 용)
  wallets          서버별 VP 지갑 (guild_id, user_id)
  wallet_ledger    VP 입출금 기록 (잔액이 맞는지 추적용)
  predictions      경기 예측 (승패/스코어/MVP)
  guild_settings   서버별 설정 (게임 채널·알림 채널)
  stocks / stock_holdings / stock_history   가상 주식(팀 주가)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 제약조건 이름 규칙을 고정해야 Alembic 마이그레이션이 환경마다 같은 이름을 만든다
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# 팀
# ---------------------------------------------------------------------------


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vlr_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tag: Mapped[str | None] = mapped_column(String(20))
    country_code: Mapped[str | None] = mapped_column(String(8))   # 예: kr (국기 이모지 변환용)
    country_name: Mapped[str | None] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(40))
    logo_url: Mapped[str | None] = mapped_column(Text)
    vlr_url: Mapped[str | None] = mapped_column(Text)
    ranking: Mapped[int | None] = mapped_column(Integer)          # /랭킹 용 (지역 랭킹 순위)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    aliases: Mapped[list[TeamAlias]] = relationship(back_populates="team", cascade="all, delete-orphan")
    members: Mapped[list[TeamMember]] = relationship(back_populates="team", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Team {self.name} vlr={self.vlr_id}>"


class TeamAlias(Base):
    """팀 검색용 별칭. alias는 정규화(소문자, 공백·기호 제거)된 값으로 저장한다."""

    __tablename__ = "team_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # manual: 직접 등록한 별칭(젠지), auto: 팀명/태그에서 자동 생성
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")

    team: Mapped[Team] = relationship(back_populates="aliases")


# ---------------------------------------------------------------------------
# 선수 / 로스터
# ---------------------------------------------------------------------------


class Player(TimestampMixin, Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vlr_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    prosettings_slug: Mapped[str | None] = mapped_column(String(120), unique=True)
    nickname: Mapped[str] = mapped_column(String(80), nullable=False)
    real_name: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(String(8))
    country_name: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str | None] = mapped_column(String(40))          # duelist, initiator ... / igl
    photo_url: Mapped[str | None] = mapped_column(Text)
    vlr_url: Mapped[str | None] = mapped_column(Text)
    prosettings_url: Mapped[str | None] = mapped_column(Text)
    current_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))

    current_team: Mapped[Team | None] = relationship(foreign_keys=[current_team_id])
    settings: Mapped[PlayerSettings | None] = relationship(
        back_populates="player", uselist=False, cascade="all, delete-orphan"
    )
    equipment: Mapped[list[Equipment]] = relationship(back_populates="player", cascade="all, delete-orphan")
    crosshair: Mapped[Crosshair | None] = relationship(
        back_populates="player", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Player {self.nickname}>"


class TeamMember(TimestampMixin, Base):
    """팀 로스터 한 줄. 코치/스태프는 players 레코드 없이 이름만 있을 수 있다."""

    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    real_name: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(String(8))
    photo_url: Mapped[str | None] = mapped_column(Text)              # VLR 로스터 사진
    # player / substitute / inactive / head_coach / coach / analyst / manager / staff
    role: Mapped[str] = mapped_column(String(30), nullable=False, server_default="player")
    is_captain: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    team: Mapped[Team] = relationship(back_populates="members")
    player: Mapped[Player | None] = relationship()

    __table_args__ = (UniqueConstraint("team_id", "name", "role", name="uq_team_members_team_name_role"),)


# ---------------------------------------------------------------------------
# 대회 / 경기
# ---------------------------------------------------------------------------


class Tournament(TimestampMixin, Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vlr_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(20))        # upcoming / ongoing / completed
    logo_url: Mapped[str | None] = mapped_column(Text)
    vlr_url: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    matches: Mapped[list[Match]] = relationship(back_populates="tournament")


class Match(TimestampMixin, Base):
    """경기. 상대 팀이 아직 DB에 없을 수 있어 팀 이름도 함께 저장한다."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vlr_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id", ondelete="SET NULL"))
    team1_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    team2_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    team1_name: Mapped[str] = mapped_column(String(120), nullable=False)
    team2_name: Mapped[str] = mapped_column(String(120), nullable=False)
    team1_score: Mapped[int | None] = mapped_column(Integer)
    team2_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="upcoming")  # upcoming/live/completed
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tournament_name: Mapped[str | None] = mapped_column(String(200))
    stage: Mapped[str | None] = mapped_column(String(120))        # 예: Playoffs – Upper Final
    vlr_url: Mapped[str | None] = mapped_column(Text)
    # 경기 상세(맵별 점수·선수 스탯) 캐시. 화면 표시용이라 JSON 통째로 보관한다.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detail_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tournament: Mapped[Tournament | None] = relationship(back_populates="matches")
    team1: Mapped[Team | None] = relationship(foreign_keys=[team1_id])
    team2: Mapped[Team | None] = relationship(foreign_keys=[team2_id])

    __table_args__ = (
        Index("ix_matches_scheduled_at", "scheduled_at"),
        Index("ix_matches_status", "status"),
        Index("ix_matches_team1_id", "team1_id"),
        Index("ix_matches_team2_id", "team2_id"),
    )


# ---------------------------------------------------------------------------
# 선수 설정 (ProSettings)
# ---------------------------------------------------------------------------


class PlayerSettings(TimestampMixin, Base):
    __tablename__ = "player_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    dpi: Mapped[int | None] = mapped_column(Integer)
    sensitivity: Mapped[float | None] = mapped_column(Float)
    edpi: Mapped[float | None] = mapped_column(Float)
    scoped_sensitivity: Mapped[float | None] = mapped_column(Float)
    polling_rate: Mapped[int | None] = mapped_column(Integer)
    windows_sensitivity: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(String(30))
    aspect_ratio: Mapped[str | None] = mapped_column(String(20))
    scaling_mode: Mapped[str | None] = mapped_column(String(30))
    refresh_rate: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)       # 표에 없던 항목까지 원본 보관
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    player: Mapped[Player] = relationship(back_populates="settings")

    __table_args__ = (Index("ix_player_settings_edpi", "edpi"),)


class Equipment(TimestampMixin, Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # mouse/keyboard/mousepad/monitor/headset
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_url: Mapped[str | None] = mapped_column(Text)

    player: Mapped[Player] = relationship(back_populates="equipment")

    __table_args__ = (UniqueConstraint("player_id", "category", name="uq_equipment_player_category"),)


class Crosshair(TimestampMixin, Base):
    __tablename__ = "crosshairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    code: Mapped[str | None] = mapped_column(Text)                  # 게임 내 가져오기 코드
    color: Mapped[str | None] = mapped_column(String(40))
    outlines: Mapped[str | None] = mapped_column(String(60))
    center_dot: Mapped[str | None] = mapped_column(String(60))
    inner_lines: Mapped[str | None] = mapped_column(String(120))
    outer_lines: Mapped[str | None] = mapped_column(String(120))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    player: Mapped[Player] = relationship(back_populates="crosshair")


# ---------------------------------------------------------------------------
# 수집 기록
# ---------------------------------------------------------------------------


class ScrapeRun(Base):
    """스크래퍼 한 번 실행 기록. /관리 상태 에서 마지막 성공/실패 시각을 보여준다."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)   # vlr / prosettings
    job: Mapped[str] = mapped_column(String(60), nullable=False)      # matches / team / player_settings ...
    target: Mapped[str | None] = mapped_column(String(200))           # 특정 팀/선수 갱신이면 그 키
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")  # running/success/failed
    items: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_scrape_runs_source_job_started", "source", "job", "started_at"),)


# 대소문자 무시 검색용 함수 인덱스 (클래스 정의 후에 컬럼을 참조해야 함)
Index("ix_teams_name_lower", func.lower(Team.name))
Index("ix_players_nickname_lower", func.lower(Player.nickname))


# ---------------------------------------------------------------------------
# VP 지갑 · 예측 게임 (가상 재화, 현금 가치 없음)
# ---------------------------------------------------------------------------


class Wallet(TimestampMixin, Base):
    """서버(guild)별 VP 지갑. 같은 사람도 서버마다 잔액이 따로다."""

    __tablename__ = "wallets"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_checkin_date: Mapped[Any | None] = mapped_column(Date)   # 마지막 출석 날짜 (한국 시간 기준)


class WalletLedger(Base):
    """잔액이 바뀔 때마다 한 줄씩 남긴다. 합계가 안 맞으면 여기서 원인을 찾는다."""

    __tablename__ = "wallet_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)   # welcome/checkin/bet/refund/payout/admin
    ref: Mapped[str | None] = mapped_column(String(60))               # 예: prediction:123
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_wallet_ledger_user", "guild_id", "user_id", "created_at"),)


class Prediction(Base):
    """경기 예측 한 건. 걸 때의 배율(odds)을 저장해 두므로 나중에 배당이 바뀌어도 영향 없다."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)       # winner / score / mvp
    pick: Mapped[str] = mapped_column(String(120), nullable=False)      # winner: '1'|'2', score: '2-1'(팀1-팀2), mvp: 선수 이름
    pick_label: Mapped[str] = mapped_column(String(160), nullable=False)  # 화면 표시용 (예: 'T1 승', 'T1 2:1', 'Meteor')
    stake: Mapped[int] = mapped_column(BigInteger, nullable=False)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="open")  # open/won/lost/void/cancelled
    payout: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    match: Mapped[Match] = relationship()

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "match_id", "kind", name="uq_predictions_one_per_kind"),
        Index("ix_predictions_match_status", "match_id", "status"),
        Index("ix_predictions_user", "guild_id", "user_id", "status"),
    )


class Profile(Base):
    """프로필 꾸미기 설정 (서버·유저별)."""

    __tablename__ = "profiles"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    theme: Mapped[str] = mapped_column(String(30), nullable=False, server_default="theme_default")
    frame: Mapped[str] = mapped_column(String(30), nullable=False, server_default="frame_none")
    title: Mapped[str] = mapped_column(String(30), nullable=False, server_default="title_none")
    fav_team: Mapped[str | None] = mapped_column(String(120))
    fav_agent: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Purchase(Base):
    """상점에서 산 꾸미기 아이템. (서버, 유저, 아이템)당 한 번만 살 수 있다."""

    __tablename__ = "purchases"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    item_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GuildSetting(Base):
    """서버별 봇 설정 (/채널설정)."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    game_channel_id: Mapped[int | None] = mapped_column(BigInteger)     # VP·예측·미니게임 명령어를 쓸 수 있는 채널
    notice_channel_id: Mapped[int | None] = mapped_column(BigInteger)   # 예측 정산 결과를 알려줄 채널
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Stock(Base):
    """가상 주식 종목 (팀). 주가는 모든 서버가 공유한다."""

    __tablename__ = "stocks"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StockHolding(Base):
    """서버·유저별 보유 주식. cost 는 보유분의 총 매수 금액(수수료 제외) — 평균 매수가 계산용."""

    __tablename__ = "stock_holdings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    cost: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")


class StockHistory(Base):
    """주가 기록 (등락률·차트용)."""

    __tablename__ = "stock_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False, server_default="tick")   # init / match / tick
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_stock_history_symbol_time", "symbol", "created_at"),)
