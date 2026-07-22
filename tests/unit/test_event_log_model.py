from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

MODEL_IMPORT_CANDIDATES = (
    "app.models.db.task_event_log:TaskEventLog",
    "app.models.task_event_log:TaskEventLog",
    "app.models.event_log:TaskEventLog",
)

REQUIRED_COLUMNS = {"seq", "task_run_id", "event_type", "payload", "created_at"}


def _load_task_event_log_model() -> type:
    errors: list[str] = []

    for candidate in MODEL_IMPORT_CANDIDATES:
        module_path, class_name = candidate.split(":", maxsplit=1)

        try:
            module = import_module(module_path)
        except ModuleNotFoundError as exc:
            errors.append(f"{candidate} -> {exc}")
            continue

        model_cls = getattr(module, class_name, None)
        if model_cls is None:
            errors.append(f"{candidate} -> missing class {class_name}")
            continue

        return model_cls

    pytest.fail(
        "Unable to import TaskEventLog from known candidates. "
        "Please align model module path with test candidates or update this test. "
        f"Tried: {MODEL_IMPORT_CANDIDATES}. Errors: {errors}"
    )


def _build_isolated_metadata(task_event_log_table: Table) -> MetaData:
    metadata = MetaData()

    # Add minimal placeholder tables for FK targets so SQLite DDL can compile in isolation.
    for foreign_key in task_event_log_table.foreign_keys:
        target_table_name = foreign_key.target_fullname.split(".", maxsplit=1)[0]
        if target_table_name not in metadata.tables:
            Table(target_table_name, metadata, Column("id", String, primary_key=True))

    task_event_log_table.to_metadata(metadata)
    return metadata


def test_task_event_log_has_required_columns() -> None:
    task_event_log_model = _load_task_event_log_model()
    table = task_event_log_model.__table__

    assert REQUIRED_COLUMNS.issubset(table.c.keys())
    assert table.c["seq"].primary_key is True
    assert table.c["task_run_id"].nullable is False
    assert table.c["event_type"].nullable is False

    created_at = table.c["created_at"]
    assert created_at.server_default is not None or created_at.default is not None


def test_task_event_log_table_can_be_created_with_sqlite_in_memory() -> None:
    task_event_log_model = _load_task_event_log_model()
    table = task_event_log_model.__table__
    metadata = _build_isolated_metadata(table)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)

    inspector = inspect(engine)
    assert "task_event_logs" in inspector.get_table_names()

    created_columns = {column["name"] for column in inspector.get_columns("task_event_logs")}
    assert REQUIRED_COLUMNS.issubset(created_columns)
