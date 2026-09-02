from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.models.db.user_account import UserAccount
from app.models.db.workspace import Workspace
from app.models.workflow import WorkflowConnection, WorkflowDefinition, WorkflowNode
from app.services.adaptor_test_workbench import (
    cleanup_expired,
    create_test_case,
    delete_test_case,
    get_execution,
    get_test_case,
    store_execution,
)


def _reset_db_runtime() -> None:
    get_settings.cache_clear()
    db_session._get_engine.cache_clear()
    db_session._get_async_engine.cache_clear()
    db_session._get_session_factory.cache_clear()
    db_session._get_async_session_factory.cache_clear()


@pytest.fixture()
def scoped_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    database_path = tmp_path / "adaptor-test-scope.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    _reset_db_runtime()
    Base.metadata.create_all(bind=db_session._get_engine())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db_session.SessionLocal() as session:
        session.add_all(
            [
                UserAccount(
                    id="usr_a",
                    email="a@example.com",
                    password_hash="unused",
                    created_at=now,
                    updated_at=now,
                ),
                UserAccount(
                    id="usr_b",
                    email="b@example.com",
                    password_hash="unused",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Workspace(
                    id="ws_a",
                    name="Workspace A",
                    slug="workspace-a",
                    owner_user_id="usr_a",
                    created_at=now,
                    updated_at=now,
                ),
                Workspace(
                    id="ws_b",
                    name="Workspace B",
                    slug="workspace-b",
                    owner_user_id="usr_b",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()
    yield
    _reset_db_runtime()


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        nodes=[
            WorkflowNode(id="input", type="input/image"),
            WorkflowNode(id="adaptor", type="processor/adaptor"),
        ],
        connections=[WorkflowConnection(source="input", target="adaptor")],
    )


def test_test_case_and_execution_are_workspace_and_user_scoped(
    scoped_database: None,
) -> None:
    test_case = create_test_case(
        _workflow(),
        "adaptor",
        [{"file_id": "file_1"}],
        workspace_id="ws_a",
        user_id="usr_a",
    )

    assert (
        get_test_case(
            test_case.test_case_id,
            workspace_id="ws_a",
            user_id="usr_a",
        )
        is not None
    )
    assert (
        get_test_case(
            test_case.test_case_id,
            workspace_id="ws_a",
            user_id="usr_b",
        )
        is None
    )
    assert (
        get_test_case(
            test_case.test_case_id,
            workspace_id="ws_b",
            user_id="usr_a",
        )
        is None
    )

    execution_id = store_execution(
        test_case.test_case_id,
        "return inputs",
        "all_upstream",
        [],
        {"status": "succeeded", "output": {"text": "ok"}},
        workspace_id="ws_a",
        user_id="usr_a",
    )
    assert get_execution(execution_id, workspace_id="ws_a", user_id="usr_a") is not None
    assert get_execution(execution_id, workspace_id="ws_a", user_id="usr_b") is None
    assert (
        delete_test_case(
            test_case.test_case_id,
            workspace_id="ws_a",
            user_id="usr_b",
        )
        is False
    )
    assert (
        delete_test_case(
            test_case.test_case_id,
            workspace_id="ws_a",
            user_id="usr_a",
        )
        is True
    )
    assert get_execution(execution_id, workspace_id="ws_a", user_id="usr_a") is None


def test_expired_test_cases_are_removed_with_cleanup(scoped_database: None) -> None:
    create_test_case(
        _workflow(),
        "adaptor",
        [],
        workspace_id="ws_a",
        user_id="usr_a",
        ttl_seconds=-1,
    )

    assert cleanup_expired() == 1
