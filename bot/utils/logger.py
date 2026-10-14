"""로깅 설정. 프로세스 시작 시 setup_logging()을 한 번 호출한다."""

from __future__ import annotations

import logging
import sys
import time


class CollapseRateLimit(logging.Filter):
    """디스코드 429(Cloudflare 차단·속도 제한) 오류를 한 줄 경고로 줄인다.

    차단 중에는 입력할 때마다 같은 오류가 나고, 오류마다 Cloudflare HTML 수십 줄이 로그에 쏟아진다.
    30초에 한 번만 한 줄로 남기고 나머지는 버린다.
    """

    INTERVAL = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._last = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if getattr(exc, "status", None) != 429:
            return True
        now = time.monotonic()
        if now - self._last < self.INTERVAL:
            return False
        self._last = now
        record.levelno, record.levelname = logging.WARNING, "WARNING"
        record.msg = "디스코드가 요청을 막고 있어요 (429, Cloudflare 차단·속도 제한). 보통 몇 분~1시간 뒤 풀립니다. 계속되면 서비스 재시작."
        record.args = ()
        record.exc_info = record.exc_text = None
        return True


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    # 429 오류는 HTML 통째로 찍히지 않게 한 줄로 (자동완성 오류는 이 로거로 나온다)
    for name in ("discord.app_commands.tree", "valobot.commands"):
        logging.getLogger(name).addFilter(CollapseRateLimit())
    # 음성 기능을 쓰지 않으므로 "PyNaCl is not installed" 경고는 숨김
    logging.getLogger("discord.client").setLevel(logging.ERROR)
    # SQL 문장 로그는 너무 많으므로 경고 이상만
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
    # 시작할 때마다 나오는 'setup plugin ...' 안내 숨김
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"valobot.{name}" if not name.startswith("valobot") else name)
