"""로깅 설정. 프로세스 시작 시 setup_logging()을 한 번 호출한다."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    # 음성 기능을 쓰지 않으므로 "PyNaCl is not installed" 경고는 숨김
    logging.getLogger("discord.client").setLevel(logging.ERROR)
    # SQL 문장 로그는 너무 많으므로 경고 이상만
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
    # 시작할 때마다 나오는 'setup plugin ...' 안내 숨김
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"valobot.{name}" if not name.startswith("valobot") else name)
