from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.db.api_invocation import ApiInvocation
from app.models.db.api_key import ApiKey
from app.models.db.user_account import UserAccount
from app.models.db.workflow_record import WorkflowRecord
from app.models.db.workflow_version_record import WorkflowVersionRecord
from app.models.workflow import Workflow, WorkflowActor, WorkflowDefinition, WorkflowVersionSnapshot
from app.repositories._workspace_filter import _require_workspace_filter

SessionFactory = Callable[[], Session]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_naive() -> datetime:
    return _utcnow().replace(tzinfo=None)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


@dataclass
class WorkflowVersionConflictError(Exception):
    workflow_id: str
    workflow_key: str
    base_version: int
    latest_version: int
    current_name: str | None
    last_saved_by: WorkflowActor | None
    updated_at: datetime


class DatabaseWorkflowStore:
    _UNSET = object()

    def __init__(self, *, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        name: str | None,
        definition: WorkflowDefinition,
        description: str | None = None,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow:
        return self.save(
            name=name,
            description=description,
            definition=definition,
            actor=actor,
            workspace_id=workspace_id,
        )

    def save(
        self,
        *,
        workflow_id: str | None = None,
        workflow_key: str | None = None,
        name: str | None,
        description: str | None = None,
        definition: WorkflowDefinition,
        base_version: int | None = None,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow:
        _require_workspace_filter(workspace_id)
        now = _utcnow_naive()

        with self._session_factory() as session:
            if workflow_id is None:
                record = WorkflowRecord(
                    id=f"wf_{uuid4()}",
                    workflow_key=workflow_key or f"wk_{uuid4()}",
                    workspace_id=workspace_id,
                    name=name,
                    description=description,
                    current_definition_json=definition.model_dump(mode="json"),
                    latest_version=1,
                    published_version=None,
                    created_by_user_id=actor.user_id if actor is not None else None,
                    last_saved_by_user_id=actor.user_id if actor is not None else None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                session.flush()
                session.add(
                    WorkflowVersionRecord(
                        id=f"wfv_{uuid4()}",
                        workflow_id=record.id,
                        version=1,
                        status="saved",
                        name=name,
                        description=description,
                        definition_json=definition.model_dump(mode="json"),
                        created_by_user_id=actor.user_id if actor is not None else None,
                        created_at=now,
                    )
                )
                session.commit()
                return self._build_workflow(session, record, include_versions=True)

            existing_record = self._resolve_record(
                session,
                workflow_id,
                workspace_id=workspace_id,
            )
            if existing_record is None:
                raise KeyError(workflow_id)
            if workflow_key is not None and existing_record.workflow_key != workflow_key:
                raise KeyError(workflow_id)
            if base_version is None or base_version != existing_record.latest_version:
                raise WorkflowVersionConflictError(
                    workflow_id=existing_record.id,
                    workflow_key=existing_record.workflow_key,
                    base_version=base_version or 0,
                    latest_version=existing_record.latest_version,
                    current_name=existing_record.name,
                    last_saved_by=self._load_actor(session, existing_record.last_saved_by_user_id),
                    updated_at=_as_aware(existing_record.updated_at),
                )

            next_version = existing_record.latest_version + 1
            existing_record.name = name if name is not None else existing_record.name
            existing_record.description = (
                description if description is not None else existing_record.description
            )
            existing_record.current_definition_json = definition.model_dump(mode="json")
            existing_record.latest_version = next_version
            if actor is not None:
                existing_record.last_saved_by_user_id = actor.user_id
            existing_record.updated_at = now
            session.add(existing_record)
            session.add(
                WorkflowVersionRecord(
                    id=f"wfv_{uuid4()}",
                    workflow_id=existing_record.id,
                    version=next_version,
                    status="saved",
                    name=existing_record.name,
                    description=existing_record.description,
                    definition_json=definition.model_dump(mode="json"),
                    created_by_user_id=actor.user_id if actor is not None else None,
                    created_at=now,
                )
            )
            session.commit()
            return self._build_workflow(session, existing_record, include_versions=True)

    def get(self, workflow_id: str, *, workspace_id: str | None = None) -> Workflow | None:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return None
            return self._build_workflow(session, record, include_versions=True)

    def list(self, *, workspace_id: str | None = None) -> list[Workflow]:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            statement: Select[tuple[WorkflowRecord]] = select(WorkflowRecord)
            statement = statement.where(WorkflowRecord.workspace_id == workspace_id)
            records = session.execute(statement).scalars().all()
            return [
                self._build_workflow(session, record, include_versions=False) for record in records
            ]

    def update(
        self,
        workflow_id: str,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
        definition: WorkflowDefinition | None = None,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow | None:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return None

            if name is not None:
                record.name = name
            if description is not self._UNSET:
                record.description = description if isinstance(description, str) else None
            if definition is not None:
                record.current_definition_json = definition.model_dump(mode="json")
            if actor is not None:
                record.last_saved_by_user_id = actor.user_id
            record.updated_at = _utcnow_naive()
            session.add(record)
            session.commit()
            return self._build_workflow(session, record, include_versions=True)

    def publish(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> WorkflowVersionSnapshot | None:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return None
            current_version = record.latest_version
            record.published_version = current_version
            record.updated_at = _utcnow_naive()
            session.add(record)

            version_record = session.execute(
                select(WorkflowVersionRecord).where(
                    WorkflowVersionRecord.workflow_id == workflow_id,
                    WorkflowVersionRecord.version == current_version,
                )
            ).scalar_one_or_none()
            if version_record is not None:
                version_record.status = "published"
                session.add(version_record)

            session.commit()
            if version_record is None:
                return None
            return self._build_version_snapshot(session, version_record)

    def restore(
        self,
        workflow_id: str,
        *,
        version: int,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow | None:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return None
            version_record = session.execute(
                select(WorkflowVersionRecord).where(
                    WorkflowVersionRecord.workflow_id == record.id,
                    WorkflowVersionRecord.version == version,
                )
            ).scalar_one_or_none()
            if version_record is None:
                return None

            record.name = version_record.name
            record.description = version_record.description
            record.current_definition_json = version_record.definition_json
            record.updated_at = _utcnow_naive()
            if actor is not None:
                record.last_saved_by_user_id = actor.user_id
            session.add(record)
            session.commit()
            return self._build_workflow(session, record, include_versions=True)

    def list_versions(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> builtins.list[WorkflowVersionSnapshot]:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return []
            version_records = (
                session.execute(
                    select(WorkflowVersionRecord)
                    .where(WorkflowVersionRecord.workflow_id == record.id)
                    .order_by(WorkflowVersionRecord.version.desc())
                )
                .scalars()
                .all()
            )
            return [self._build_version_snapshot(session, item) for item in version_records]

    def delete(self, workflow_id: str, *, workspace_id: str | None = None) -> bool:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return False
            # Keep SQLite deployments correct even when a legacy connection has
            # foreign-key enforcement disabled. The database constraints added
            # in 0015 remain the primary integrity boundary.
            session.execute(sql_delete(ApiInvocation).where(ApiInvocation.workflow_id == record.id))
            session.execute(sql_delete(ApiKey).where(ApiKey.workflow_id == record.id))
            session.execute(
                sql_delete(WorkflowVersionRecord).where(
                    WorkflowVersionRecord.workflow_id == record.id
                )
            )
            session.flush()
            session.delete(record)
            session.commit()
            return True

    def list_paginated(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        query: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[builtins.list[Workflow], int]:
        _require_workspace_filter(workspace_id)
        safe_page = max(page, 1)
        safe_limit = max(limit, 1)
        sort_field = sort_by if sort_by in {"updated_at", "created_at", "name"} else "updated_at"
        descending = sort_order.lower() != "asc"

        with self._session_factory() as session:
            statement: Select[tuple[WorkflowRecord]] = select(WorkflowRecord)
            statement = statement.where(WorkflowRecord.workspace_id == workspace_id)
            normalized_query = (query or "").strip()
            if normalized_query:
                like_value = f"%{normalized_query.lower()}%"
                statement = statement.where(
                    or_(
                        func.lower(func.coalesce(WorkflowRecord.name, "")).like(like_value),
                        func.lower(func.coalesce(WorkflowRecord.description, "")).like(like_value),
                    )
                )

            total = session.execute(
                select(func.count()).select_from(statement.subquery())
            ).scalar_one()

            sort_column = getattr(WorkflowRecord, sort_field)
            statement = statement.order_by(
                sort_column.asc() if not descending else sort_column.desc()
            )
            statement = statement.offset((safe_page - 1) * safe_limit).limit(safe_limit)
            records = session.execute(statement).scalars().all()
            workflows = [
                self._build_workflow(session, item, include_versions=False) for item in records
            ]
            return workflows, int(total)

    def find_duplicate_dag_hash(
        self,
        workflow_id: str,
        dag_hash: str,
        *,
        workspace_id: str | None = None,
    ) -> int | None:
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return None
            version_record = session.execute(
                select(WorkflowVersionRecord).where(
                    WorkflowVersionRecord.workflow_id == record.id,
                    WorkflowVersionRecord.dag_hash == dag_hash,
                )
            ).scalar_one_or_none()
            if version_record is not None:
                return version_record.version
            return None

    def get_version(
        self,
        workflow_id: str,
        version: int,
        *,
        workspace_id: str | None = None,
    ) -> WorkflowVersionSnapshot | None:
        """Get a specific version snapshot."""
        _require_workspace_filter(workspace_id)
        with self._session_factory() as session:
            record = self._resolve_record(session, workflow_id, workspace_id=workspace_id)
            if record is None:
                return None
            version_record = session.execute(
                select(WorkflowVersionRecord).where(
                    WorkflowVersionRecord.workflow_id == record.id,
                    WorkflowVersionRecord.version == version,
                )
            ).scalar_one_or_none()
            if version_record is None:
                return None
            return self._build_version_snapshot(session, version_record)

    def publish_new_workflow(
        self,
        *,
        name: str | None,
        description: str | None,
        definition: WorkflowDefinition,
        dag_hash: str,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow:
        """Create a new workflow and publish v1 atomically in a single session."""
        _require_workspace_filter(workspace_id)
        now = _utcnow_naive()

        with self._session_factory() as session:
            record = WorkflowRecord(
                id=f"wf_{uuid4()}",
                workflow_key=f"wk_{uuid4()}",
                workspace_id=workspace_id,
                name=name,
                description=description,
                current_definition_json=definition.model_dump(mode="json"),
                latest_version=1,
                published_version=1,
                created_by_user_id=actor.user_id if actor is not None else None,
                last_saved_by_user_id=actor.user_id if actor is not None else None,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.flush()

            version_record = WorkflowVersionRecord(
                id=f"wfv_{uuid4()}",
                workflow_id=record.id,
                version=1,
                status="published",
                name=name,
                description=description,
                definition_json=definition.model_dump(mode="json"),
                dag_hash=dag_hash,
                created_by_user_id=actor.user_id if actor is not None else None,
                created_at=now,
            )
            session.add(version_record)
            session.commit()
            return self._build_workflow(session, record, include_versions=True)

    def publish_next_version(
        self,
        workflow_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        definition: WorkflowDefinition,
        dag_hash: str,
        base_version: int | None = None,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow:
        """Publish a new version of an existing workflow atomically in a single session.

        Raises WorkflowVersionConflictError if base_version doesn't match.
        Raises KeyError if workflow_id doesn't exist.
        """
        _require_workspace_filter(workspace_id)
        now = _utcnow_naive()

        with self._session_factory() as session:
            existing_record = self._resolve_record(
                session,
                workflow_id,
                workspace_id=workspace_id,
            )
            if existing_record is None:
                raise KeyError(workflow_id)

            if base_version is None or base_version != existing_record.latest_version:
                raise WorkflowVersionConflictError(
                    workflow_id=existing_record.id,
                    workflow_key=existing_record.workflow_key,
                    base_version=base_version or 0,
                    latest_version=existing_record.latest_version,
                    current_name=existing_record.name,
                    last_saved_by=self._load_actor(session, existing_record.last_saved_by_user_id),
                    updated_at=_as_aware(existing_record.updated_at),
                )

            next_version = existing_record.latest_version + 1
            existing_record.name = name if name is not None else existing_record.name
            existing_record.description = (
                description if description is not None else existing_record.description
            )
            existing_record.current_definition_json = definition.model_dump(mode="json")
            existing_record.latest_version = next_version
            existing_record.published_version = next_version
            if actor is not None:
                existing_record.last_saved_by_user_id = actor.user_id
            existing_record.updated_at = now
            session.add(existing_record)

            version_record = WorkflowVersionRecord(
                id=f"wfv_{uuid4()}",
                workflow_id=existing_record.id,
                version=next_version,
                status="published",
                name=existing_record.name,
                description=existing_record.description,
                definition_json=definition.model_dump(mode="json"),
                dag_hash=dag_hash,
                created_by_user_id=actor.user_id if actor is not None else None,
                created_at=now,
            )
            session.add(version_record)
            session.commit()
            return self._build_workflow(session, existing_record, include_versions=True)

    def _resolve_record(
        self,
        session: Session,
        workflow_identifier: str,
        *,
        workspace_id: str | None = None,
    ) -> WorkflowRecord | None:
        record = session.get(WorkflowRecord, workflow_identifier)
        if record is not None:
            if workspace_id is None or record.workspace_id == workspace_id:
                return record
            return None
        statement = select(WorkflowRecord).where(WorkflowRecord.workflow_key == workflow_identifier)
        statement = statement.where(WorkflowRecord.workspace_id == workspace_id)
        return session.execute(statement).scalar_one_or_none()

    def _build_workflow(
        self, session: Session, record: WorkflowRecord, *, include_versions: bool
    ) -> Workflow:
        versions: list[WorkflowVersionSnapshot] = []
        if include_versions:
            version_records = (
                session.execute(
                    select(WorkflowVersionRecord)
                    .where(WorkflowVersionRecord.workflow_id == record.id)
                    .order_by(WorkflowVersionRecord.version.desc())
                )
                .scalars()
                .all()
            )
            versions = [self._build_version_snapshot(session, item) for item in version_records]

        return Workflow(
            id=record.id,
            workflow_key=record.workflow_key,
            workspace_id=record.workspace_id,
            name=record.name,
            description=record.description,
            definition=WorkflowDefinition.model_validate(record.current_definition_json),
            created_at=_as_aware(record.created_at),
            updated_at=_as_aware(record.updated_at),
            published_version=record.published_version,
            latest_version=record.latest_version,
            created_by=self._load_actor(session, record.created_by_user_id),
            last_saved_by=self._load_actor(session, record.last_saved_by_user_id),
            versions=versions,
        )

    def _build_version_snapshot(
        self, session: Session, version_record: WorkflowVersionRecord
    ) -> WorkflowVersionSnapshot:
        return WorkflowVersionSnapshot(
            version=version_record.version,
            status="published" if version_record.status == "published" else "saved",
            name=version_record.name,
            description=version_record.description,
            definition=WorkflowDefinition.model_validate(version_record.definition_json),
            dag_hash=version_record.dag_hash,
            created_at=_as_aware(version_record.created_at),
            created_by=self._load_actor(session, version_record.created_by_user_id),
        )

    def _load_actor(self, session: Session, user_id: str | None) -> WorkflowActor | None:
        if user_id is None:
            return None
        user = session.get(UserAccount, user_id)
        if user is None:
            return None
        return WorkflowActor(user_id=user.id, email=user.email, name=user.name)
