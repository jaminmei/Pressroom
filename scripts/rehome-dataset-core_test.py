from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("rehome-dataset-core.py")


def _sha256(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    database_path = tmp_path / "corgi.db"
    storage_root = tmp_path / "storage"
    manifest_path = tmp_path / "preconditions.json"
    source_dataset_id = "ts_corgi"
    source_dir = storage_root / "test_sets" / source_dataset_id / "documents"
    source_dir.mkdir(parents=True)
    documents = []
    for document_id, filename, content in (
        ("doc_corgi_1", "one.pdf", b"corgi one"),
        ("doc_corgi_2", "two.pdf", b"corgi two"),
    ):
        path = source_dir / f"{document_id}_{filename}"
        path.write_bytes(content)
        documents.append(
            {
                "id": document_id,
                "storage_path": str(path.relative_to(storage_root)),
                "sha256": _sha256(path),
            }
        )
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE workspaces (id TEXT PRIMARY KEY);
            CREATE TABLE test_sets (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                workspace_id TEXT, document_count INTEGER NOT NULL,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE test_documents (
                id TEXT PRIMARY KEY, test_set_id TEXT NOT NULL, filename TEXT NOT NULL,
                mime_type TEXT NOT NULL, size_bytes INTEGER, storage_path TEXT NOT NULL UNIQUE,
                page_count INTEGER, created_at TEXT
            );
            CREATE TABLE ground_truths (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version INTEGER NOT NULL,
                source TEXT NOT NULL, format TEXT NOT NULL, content TEXT NOT NULL,
                source_task_run_id TEXT, notes TEXT, created_at TEXT
            );
            CREATE TABLE evaluation_runs (id TEXT PRIMARY KEY, test_set_id TEXT NOT NULL);
            CREATE TABLE evaluation_results (id TEXT PRIMARY KEY, evaluation_run_id TEXT NOT NULL);
            """
        )
        connection.executemany(
            "INSERT INTO workspaces VALUES (?)", [("ws_legacy",), ("ws_personal",)]
        )
        connection.execute(
            "INSERT INTO test_sets VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_dataset_id, "Corgi", "source", "ws_legacy", 2, "now", "now"),
        )
        for document in documents:
            connection.execute(
                "INSERT INTO test_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document["id"],
                    source_dataset_id,
                    f"{document['id'][-1]}.pdf",
                    "application/pdf",
                    9,
                    document["storage_path"],
                    1,
                    "now",
                ),
            )
            connection.execute(
                "INSERT INTO ground_truths VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"gt_{document['id']}",
                    document["id"],
                    1,
                    "manual",
                    "markdown",
                    "# Corgi",
                    None,
                    None,
                    "now",
                ),
            )
        connection.execute(
            "INSERT INTO evaluation_runs VALUES ('eval_corgi', ?)", (source_dataset_id,)
        )
        connection.execute("INSERT INTO evaluation_results VALUES ('result_corgi', 'eval_corgi')")
    manifest_path.write_text(
        json.dumps(
            {
                "database_url": f"sqlite:///{database_path}",
                "storage_root": str(storage_root),
                "journal_path": str(tmp_path / "journal"),
                "source_workspace_id": "ws_legacy",
                "documents": documents,
            }
        ),
        encoding="utf-8",
    )
    return database_path, manifest_path, storage_root


def _run(manifest_path: Path, mapping_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-dataset-id",
            "ts_corgi",
            "--target-workspace-id",
            "ws_personal",
            "--target-owner-user-id",
            "usr_personal",
            "--operation-id",
            "rehome-corgi-1",
            "--precondition-manifest",
            str(manifest_path),
            "--mapping-output",
            str(mapping_path),
            f"--{mode}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_dry_run_is_read_only_and_writes_plan(tmp_path: Path) -> None:
    database_path, manifest_path, storage_root = _fixture(tmp_path)
    mapping_path = tmp_path / "mapping.json"

    result = _run(manifest_path, mapping_path, "dry-run")

    assert result.returncode == 0, result.stderr
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["state"] == "planned"
    assert not (storage_root / "test_sets" / ".rehome").exists()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM test_sets").fetchone() == (1,)


def test_apply_copies_only_core_then_rollback_removes_target_artifacts(tmp_path: Path) -> None:
    database_path, manifest_path, storage_root = _fixture(tmp_path)
    mapping_path = tmp_path / "mapping.json"

    applied = _run(manifest_path, mapping_path, "apply")

    assert applied.returncode == 0, applied.stderr
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert mapping["state"] == "applied"
    assert len(mapping["documents"]) == len(mapping["ground_truths"]) == 2
    target_dataset_id = mapping["target_dataset_id"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT workspace_id FROM test_sets WHERE id = ?", (target_dataset_id,)
        ).fetchone() == ("ws_personal",)
        assert connection.execute(
            "SELECT COUNT(*) FROM test_documents WHERE test_set_id = ?", (target_dataset_id,)
        ).fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM ground_truths").fetchone() == (4,)
        assert connection.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM evaluation_results").fetchone() == (1,)
    assert (storage_root / "test_sets" / target_dataset_id).is_dir()

    rolled_back = _run(manifest_path, mapping_path, "rollback")

    assert rolled_back.returncode == 0, rolled_back.stderr
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["state"] == "rolled_back"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM test_sets").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM ground_truths").fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone() == (1,)
    assert not (storage_root / "test_sets" / target_dataset_id).exists()
