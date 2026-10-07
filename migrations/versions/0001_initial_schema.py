"""초기 스키마: 팀, 선수, 로스터, 대회, 경기, 선수 설정, 장비, 크로스헤어, 수집 기록

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # --- teams ---------------------------------------------------------------
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vlr_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("tag", sa.String(20)),
        sa.Column("country_code", sa.String(8)),
        sa.Column("country_name", sa.String(80)),
        sa.Column("region", sa.String(40)),
        sa.Column("logo_url", sa.Text()),
        sa.Column("vlr_url", sa.Text()),
        sa.Column("ranking", sa.Integer()),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
        sa.UniqueConstraint("vlr_id", name="uq_teams_vlr_id"),
    )
    op.create_index("ix_teams_name_lower", "teams", [sa.text("lower(name)")])

    # --- team_aliases --------------------------------------------------------
    op.create_table(
        "team_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(80), nullable=False),
        sa.Column("source", sa.String(20), server_default="manual", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_team_aliases"),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_team_aliases_team_id_teams", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("alias", name="uq_team_aliases_alias"),
    )

    # --- players -------------------------------------------------------------
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vlr_id", sa.Integer()),
        sa.Column("prosettings_slug", sa.String(120)),
        sa.Column("nickname", sa.String(80), nullable=False),
        sa.Column("real_name", sa.String(120)),
        sa.Column("country_code", sa.String(8)),
        sa.Column("country_name", sa.String(80)),
        sa.Column("role", sa.String(40)),
        sa.Column("photo_url", sa.Text()),
        sa.Column("vlr_url", sa.Text()),
        sa.Column("prosettings_url", sa.Text()),
        sa.Column("current_team_id", sa.Integer()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
        sa.ForeignKeyConstraint(
            ["current_team_id"], ["teams.id"], name="fk_players_current_team_id_teams", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("vlr_id", name="uq_players_vlr_id"),
        sa.UniqueConstraint("prosettings_slug", name="uq_players_prosettings_slug"),
    )
    op.create_index("ix_players_nickname_lower", "players", [sa.text("lower(nickname)")])

    # --- team_members --------------------------------------------------------
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer()),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("real_name", sa.String(120)),
        sa.Column("country_code", sa.String(8)),
        sa.Column("role", sa.String(30), server_default="player", nullable=False),
        sa.Column("is_captain", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_team_members"),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_team_members_team_id_teams", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name="fk_team_members_player_id_players", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("team_id", "name", "role", name="uq_team_members_team_name_role"),
    )

    # --- tournaments ---------------------------------------------------------
    op.create_table(
        "tournaments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vlr_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("region", sa.String(40)),
        sa.Column("status", sa.String(20)),
        sa.Column("logo_url", sa.Text()),
        sa.Column("vlr_url", sa.Text()),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_tournaments"),
        sa.UniqueConstraint("vlr_id", name="uq_tournaments_vlr_id"),
    )

    # --- matches -------------------------------------------------------------
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vlr_id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer()),
        sa.Column("team1_id", sa.Integer()),
        sa.Column("team2_id", sa.Integer()),
        sa.Column("team1_name", sa.String(120), nullable=False),
        sa.Column("team2_name", sa.String(120), nullable=False),
        sa.Column("team1_score", sa.Integer()),
        sa.Column("team2_score", sa.Integer()),
        sa.Column("status", sa.String(20), server_default="upcoming", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("tournament_name", sa.String(200)),
        sa.Column("stage", sa.String(120)),
        sa.Column("vlr_url", sa.Text()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_matches"),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournaments.id"], name="fk_matches_tournament_id_tournaments", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["team1_id"], ["teams.id"], name="fk_matches_team1_id_teams", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team2_id"], ["teams.id"], name="fk_matches_team2_id_teams", ondelete="SET NULL"),
        sa.UniqueConstraint("vlr_id", name="uq_matches_vlr_id"),
    )
    op.create_index("ix_matches_scheduled_at", "matches", ["scheduled_at"])
    op.create_index("ix_matches_status", "matches", ["status"])
    op.create_index("ix_matches_team1_id", "matches", ["team1_id"])
    op.create_index("ix_matches_team2_id", "matches", ["team2_id"])

    # --- player_settings -----------------------------------------------------
    op.create_table(
        "player_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("dpi", sa.Integer()),
        sa.Column("sensitivity", sa.Float()),
        sa.Column("edpi", sa.Float()),
        sa.Column("scoped_sensitivity", sa.Float()),
        sa.Column("polling_rate", sa.Integer()),
        sa.Column("windows_sensitivity", sa.Integer()),
        sa.Column("resolution", sa.String(30)),
        sa.Column("aspect_ratio", sa.String(20)),
        sa.Column("scaling_mode", sa.String(30)),
        sa.Column("refresh_rate", sa.Integer()),
        sa.Column("raw", postgresql.JSONB()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_player_settings"),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name="fk_player_settings_player_id_players", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("player_id", name="uq_player_settings_player_id"),
    )
    op.create_index("ix_player_settings_edpi", "player_settings", ["edpi"])

    # --- equipment -----------------------------------------------------------
    op.create_table(
        "equipment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("product_url", sa.Text()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_equipment"),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name="fk_equipment_player_id_players", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("player_id", "category", name="uq_equipment_player_category"),
    )

    # --- crosshairs ----------------------------------------------------------
    op.create_table(
        "crosshairs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text()),
        sa.Column("color", sa.String(40)),
        sa.Column("outlines", sa.String(60)),
        sa.Column("center_dot", sa.String(60)),
        sa.Column("inner_lines", sa.String(120)),
        sa.Column("outer_lines", sa.String(120)),
        sa.Column("raw", postgresql.JSONB()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_crosshairs"),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name="fk_crosshairs_player_id_players", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("player_id", name="uq_crosshairs_player_id"),
    )

    # --- scrape_runs ---------------------------------------------------------
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("job", sa.String(60), nullable=False),
        sa.Column("target", sa.String(200)),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_scrape_runs"),
    )
    op.create_index("ix_scrape_runs_source_job_started", "scrape_runs", ["source", "job", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_scrape_runs_source_job_started", table_name="scrape_runs")
    op.drop_table("scrape_runs")
    op.drop_table("crosshairs")
    op.drop_table("equipment")
    op.drop_index("ix_player_settings_edpi", table_name="player_settings")
    op.drop_table("player_settings")
    for ix in ("ix_matches_team2_id", "ix_matches_team1_id", "ix_matches_status", "ix_matches_scheduled_at"):
        op.drop_index(ix, table_name="matches")
    op.drop_table("matches")
    op.drop_table("tournaments")
    op.drop_table("team_members")
    op.drop_index("ix_players_nickname_lower", table_name="players")
    op.drop_table("players")
    op.drop_table("team_aliases")
    op.drop_index("ix_teams_name_lower", table_name="teams")
    op.drop_table("teams")
