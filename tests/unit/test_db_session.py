from __future__ import annotations

import importlib
import sys


def test_db_session_module_import_is_lazy(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    sys.modules.pop("app.db.session", None)

    session_module = importlib.import_module("app.db.session")

    assert callable(session_module.SessionLocal)
    assert callable(session_module.AsyncSessionLocal)
