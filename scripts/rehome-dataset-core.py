#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# uv run python scripts/rehome-dataset-core.py \
#   --source-dataset-id SOURCE --target-workspace-id TARGET \
#   --target-owner-user-id OWNER --operation-id OPERATION \
#   --precondition-manifest manifest.json --mapping-output mapping.json --dry-run

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterator
from uuid import uuid4

STATES: Final = ("planned", "files_copied", "rows_committed", "applied", "rolled_back")


class RehomeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    source_dataset_id: str
    target_workspace_id: str
    target_owner_user_id: str
    operation_id: str
    manifest_path: Path
    mapping_output: Path
    mode: str


@dataclass(frozen=True, slots=True)
class Manifest:
    database_path: Path
    storage_root: Path
    journal_path: Path
    source_workspace_id: str
    documents: tuple[tuple[str, str, str], ...]


def parse_args() -> Settings:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset-id", required=True)
    parser.add_argument("--target-workspace-id", required=True)
    parser.add_argument("--target-owner-user-id", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--precondition-manifest", type=Path, required=True)
    parser.add_argument("--mapping-output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    return Settings(
        source_dataset_id=args.source_dataset_id,
        target_workspace_id=args.target_workspace_id,
        target_owner_user_id=args.target_owner_user_id,
        operation_id=args.operation_id,
        manifest_path=args.precondition_manifest,
        mapping_output=args.mapping_output,
        mode="dry-run" if args.dry_run else "apply" if args.apply else "rollback",
    )


def load_manifest(path: Path) -> Manifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        database_url = payload["database_url"]
        prefix = "sqlite:///"
        if not isinstance(database_url, str) or not database_url.startswith(prefix):
            raise RehomeError("precondition manifest requires a sqlite:/// database_url")
        documents = tuple(
            (item["id"], item["storage_path"], item["sha256"]) for item in payload["documents"]
        )
        if not documents:
            raise RehomeError("precondition manifest must name at least one document")
        return Manifest(
            database_path=Path(database_url.removeprefix(prefix)),
            storage_root=Path(payload["storage_root"]),
            journal_path=Path(payload["journal_path"]),
            source_workspace_id=payload["source_workspace_id"],
            documents=documents,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RehomeError(f"invalid precondition manifest: {error}") from error


@contextmanager
def operation_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RehomeError(f"operation lock already held: {path}") from error
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def journal_file(manifest: Manifest, operation_id: str) -> Path:
    return manifest.journal_path / f"{operation_id}.json"


def read_journal(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RehomeError(f"invalid operation journal: {error}") from error
    if not isinstance(payload, dict) or payload.get("state") not in STATES:
        raise RehomeError("invalid operation journal state")
    return payload


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def source_rows(
    connection: sqlite3.Connection, settings: Settings, manifest: Manifest
) -> tuple[sqlite3.Row, list[sqlite3.Row], list[sqlite3.Row]]:
    connection.row_factory = sqlite3.Row
    dataset = connection.execute(
        "SELECT * FROM test_sets WHERE id = ? AND workspace_id = ?",
        (settings.source_dataset_id, manifest.source_workspace_id),
    ).fetchone()
    if dataset is None:
        raise RehomeError("source dataset is absent or outside the manifest workspace")
    documents = connection.execute(
        "SELECT * FROM test_documents WHERE test_set_id = ? ORDER BY id",
        (settings.source_dataset_id,),
    ).fetchall()
    expected = {
        document_id: (storage_path, digest)
        for document_id, storage_path, digest in manifest.documents
    }
    if {row["id"] for row in documents} != set(expected):
        raise RehomeError("source document IDs differ from precondition manifest")
    for row in documents:
        source_file = manifest.storage_root / expected[row["id"]][0]
        if (
            source_file != manifest.storage_root / row["storage_path"]
            or sha256(source_file) != expected[row["id"]][1]
        ):
            raise RehomeError(f"source file precondition failed: {row['id']}")
    ground_truths = connection.execute(
        "SELECT * FROM ground_truths WHERE document_id IN "
        "(SELECT id FROM test_documents WHERE test_set_id = ?) ORDER BY id",
        (settings.source_dataset_id,),
    ).fetchall()
    return dataset, documents, ground_truths


def plan(settings: Settings, manifest: Manifest) -> dict[str, object]:
    with sqlite3.connect(manifest.database_path) as connection:
        dataset, documents, ground_truths = source_rows(connection, settings, manifest)
    target_dataset_id = f"ts_{uuid4()}"
    document_mapping = [
        {
            "source_id": row["id"],
            "target_id": f"doc_{uuid4()}",
            "filename": row["filename"],
            "source_storage_path": row["storage_path"],
        }
        for row in documents
    ]
    lookup = {entry["source_id"]: entry["target_id"] for entry in document_mapping}
    return {
        "operation_id": settings.operation_id,
        "state": "planned",
        "source_dataset_id": settings.source_dataset_id,
        "target_dataset_id": target_dataset_id,
        "target_workspace_id": settings.target_workspace_id,
        "target_owner_user_id": settings.target_owner_user_id,
        "source_dataset_name": dataset["name"],
        "documents": document_mapping,
        "ground_truths": [
            {
                "source_id": row["id"],
                "target_id": f"gt_{uuid4()}",
                "target_document_id": lookup[row["document_id"]],
            }
            for row in ground_truths
        ],
        "excluded": ["evaluation_runs", "evaluation_results", "workflows", "task_runs"],
    }


def copy_files(journal: dict[str, object], manifest: Manifest) -> None:
    target_dataset_id = str(journal["target_dataset_id"])
    documents = journal["documents"]
    if not isinstance(documents, list):
        raise RehomeError("invalid journal document mapping")
    final_dir = manifest.storage_root / "test_sets" / target_dataset_id
    temp_dir = manifest.storage_root / "test_sets" / ".rehome" / str(journal["operation_id"])
    if final_dir.exists() or temp_dir.exists():
        raise RehomeError("target storage path already exists")
    for mapping in documents:
        if not isinstance(mapping, dict):
            raise RehomeError("invalid document mapping")
        source = manifest.storage_root / str(mapping["source_storage_path"])
        target = temp_dir / "documents" / f"{mapping['target_id']}_{mapping['filename']}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if sha256(source) != sha256(target):
            raise RehomeError(f"copied file checksum mismatch: {mapping['source_id']}")
        mapping["target_storage_path"] = str(target.relative_to(manifest.storage_root)).replace(
            str(temp_dir.relative_to(manifest.storage_root)),
            str(final_dir.relative_to(manifest.storage_root)),
            1,
        )
        mapping["sha256"] = sha256(target)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.replace(final_dir)


def insert_rows(journal: dict[str, object], manifest: Manifest) -> None:
    documents = journal["documents"]
    ground_truths = journal["ground_truths"]
    if not isinstance(documents, list) or not isinstance(ground_truths, list):
        raise RehomeError("invalid journal mappings")
    with sqlite3.connect(manifest.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        source = connection.execute(
            "SELECT * FROM test_sets WHERE id = ?", (journal["source_dataset_id"],)
        ).fetchone()
        if source is None:
            raise RehomeError("source dataset disappeared before row commit")
        connection.execute(
            "INSERT INTO test_sets "
            "(id, name, description, workspace_id, document_count, created_at, updated_at) "
            "SELECT ?, name, description, ?, ?, created_at, updated_at "
            "FROM test_sets WHERE id = ?",
            (
                journal["target_dataset_id"],
                journal["target_workspace_id"],
                len(documents),
                journal["source_dataset_id"],
            ),
        )
        for mapping in documents:
            if not isinstance(mapping, dict):
                raise RehomeError("invalid document mapping")
            connection.execute(
                "INSERT INTO test_documents "
                "(id, test_set_id, filename, mime_type, size_bytes, storage_path, "
                "page_count, created_at) "
                "SELECT ?, ?, filename, mime_type, size_bytes, ?, page_count, created_at "
                "FROM test_documents WHERE id = ?",
                (
                    mapping["target_id"],
                    journal["target_dataset_id"],
                    mapping["target_storage_path"],
                    mapping["source_id"],
                ),
            )
        for mapping in ground_truths:
            if not isinstance(mapping, dict):
                raise RehomeError("invalid ground-truth mapping")
            connection.execute(
                "INSERT INTO ground_truths "
                "(id, document_id, version, source, format, content, source_task_run_id, "
                "notes, created_at) "
                "SELECT ?, ?, version, source, format, content, source_task_run_id, "
                "notes, created_at FROM ground_truths WHERE id = ?",
                (mapping["target_id"], mapping["target_document_id"], mapping["source_id"]),
            )


def rollback(journal: dict[str, object], manifest: Manifest) -> None:
    target_dataset_id = str(journal["target_dataset_id"])
    with sqlite3.connect(manifest.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM ground_truths WHERE document_id IN "
            "(SELECT id FROM test_documents WHERE test_set_id = ?)",
            (target_dataset_id,),
        )
        connection.execute("DELETE FROM test_documents WHERE test_set_id = ?", (target_dataset_id,))
        connection.execute(
            "DELETE FROM test_sets WHERE id = ? AND workspace_id = ?",
            (target_dataset_id, journal["target_workspace_id"]),
        )
    shutil.rmtree(manifest.storage_root / "test_sets" / target_dataset_id, ignore_errors=True)


def run(settings: Settings) -> int:
    manifest = load_manifest(settings.manifest_path)
    journal_path = journal_file(manifest, settings.operation_id)
    if settings.mode == "dry-run":
        journal = plan(settings, manifest)
        write_json(settings.mapping_output, journal)
        print(json.dumps(journal, sort_keys=True))
        return 0
    with operation_lock(manifest.journal_path / f"{settings.operation_id}.lock"):
        if settings.mode == "rollback" and not journal_path.exists():
            raise RehomeError("rollback requires an existing operation journal")
        journal = read_journal(journal_path) if journal_path.exists() else plan(settings, manifest)
        if settings.mode == "rollback":
            rollback(journal, manifest)
            journal["state"] = "rolled_back"
        else:
            if journal["state"] == "planned":
                write_json(journal_path, journal)
                copy_files(journal, manifest)
                journal["state"] = "files_copied"
                write_json(journal_path, journal)
            if journal["state"] == "files_copied":
                insert_rows(journal, manifest)
                journal["state"] = "rows_committed"
                write_json(journal_path, journal)
            if journal["state"] == "rows_committed":
                journal["state"] = "applied"
        write_json(journal_path, journal)
        write_json(settings.mapping_output, journal)
        print(json.dumps(journal, sort_keys=True))
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except (RehomeError, OSError, sqlite3.DatabaseError) as error:
        print(f"rehome failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
