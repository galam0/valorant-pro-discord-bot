"""테스트용: 설치되지 않은 무거운 패키지(aiohttp, sqlalchemy 등)를 가짜로 대체한다. 실제 패키지가 있으면 그대로 쓴다."""

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from unittest.mock import MagicMock

_MISSING = tuple(n for n in ("aiohttp", "discord", "sqlalchemy", "asyncpg", "apscheduler", "alembic")
                 if importlib.util.find_spec(n) is None)


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in _MISSING:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        mod = MagicMock()
        mod.__path__ = []
        mod.__spec__ = spec
        return mod

    def exec_module(self, module):
        pass


if _MISSING:
    sys.meta_path.insert(0, _StubFinder())
