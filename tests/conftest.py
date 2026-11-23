from __future__ import annotations

import pytest

from prospector.config import AppPaths
from prospector.database.engine import Database
from prospector.database.repository import Repository


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / "dados"
    return AppPaths(root, root / "prospector.sqlite3", root / "backups", root / "evidence", root / "exports", root / "imports", root / "logs", root / "models")


@pytest.fixture
def database(paths):
    result = Database(paths)
    result.initialize()
    return result


@pytest.fixture
def repo(database):
    return Repository(database)
