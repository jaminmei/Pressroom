from __future__ import annotations

import builtins
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.models.workflow import Workflow, WorkflowActor, WorkflowDefinition, WorkflowVersionSnapshot
from app.repositories._workspace_filter import _require_workspace_filter


@dataclass(frozen=True, slots=True)
class WorkflowDeletionImpact:
    workflow_id: str
    task_runs: int = 0
    active_task_runs: int = 0
    evaluation_runs: int = 0
    active_evaluation_runs: int = 0
    api_keys: int = 0
    active_api_keys: int = 0

    @property
    def can_delete(self) -> bool:
        return True


class WorkflowVersionConflictError(Exception):
    def __init__(
        self,
        *,
        workflow_id: str,
        workflow_key: str | None,
        base_version: int,
        latest_version: int,
        current_name: str | None,
        last_saved_by: WorkflowActor | None,
        updated_at: datetime,
    ) -> None:
        super().__init__("workflow version conflict")
        self.workflow_id = workflow_id
        self.workflow_key = workflow_key
        self.base_version = base_version
        self.latest_version = latest_version
        self.current_name = current_name
        self.last_saved_by = last_saved_by
        self.updated_at = updated_at


class WorkflowStore:
    _UNSET = object()

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    @staticmethod
    def _copy_workflow(workflow: Workflow) -> Workflow:
        return workflow.model_copy(deep=True)

    @staticmethod
    def _copy_snapshot(snapshot: WorkflowVersionSnapshot) -> WorkflowVersionSnapshot:
        return snapshot.model_copy(deep=True)

    def _workflow_key_exists(self, workflow_key: str) -> bool:
        return any(workflow.workflow_key == workflow_key for workflow in self._workflows.values())

    def _generate_workflow_key(self) -> str:
        workflow_key = f"wk_{uuid4()}"
        while self._workflow_key_exists(workflow_key):
            workflow_key = f"wk_{uuid4()}"
        return workflow_key

    def create(
        self,
        *,
        name: str | None,
        definition: WorkflowDefinition,
        description: str | None = None,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow:
        _require_workspace_filter(workspace_id)
        workflow_id = f"wf_{uuid4()}"
        now = datetime.now(timezone.utc)

        workflow = Workflow(
            id=workflow_id,
            workflow_key=self._generate_workflow_key(),
            workspace_id=workspace_id,
            name=name,
            description=description,
            definition=definition,
            created_at=now,
            updated_at=now,
            latest_version=1,
            published_version=None,
            created_by=actor,
            last_saved_by=actor,
            versions=[],
        )
        workflow.versions.append(
            WorkflowVersionSnapshot(
                version=1,
                status="saved",
                name=name,
                description=description,
                definition=definition.model_copy(deep=True),
                created_at=now,
                created_by=actor,
            )
        )
        self._workflows[workflow_id] = self._copy_workflow(workflow)
        return self._copy_workflow(workflow)

    def get(self, workflow_id: str, *, workspace_id: str | None = None) -> Workflow | None:
        _require_workspace_filter(workspace_id)
        resolved_id = self._resolve_workflow_id(workflow_id, workspace_id=workspace_id)
        if resolved_id is None:
            return None
        workflow = self._workflows.get(resolved_id)
        if workflow is None:
            return None
        return self._copy_workflow(workflow)

    def list(self, *, workspace_id: str | None = None) -> list[Workflow]:
        _require_workspace_filter(workspace_id)
        return [
            self._copy_workflow(workflow)
            for workflow in self._workflows.values()
            if workflow.workspace_id == workspace_id
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
        existing = self.get(workflow_id, workspace_id=workspace_id)
        if existing is None:
            return None

        updated = existing.model_copy(deep=True)
        if name is not None:
            updated.name = name
        if description is not self._UNSET:
            updated.description = description if isinstance(description, str) else None
        if definition is not None:
            updated.definition = definition
        if actor is not None:
            updated.last_saved_by = actor
        updated.updated_at = datetime.now(timezone.utc)

        self._workflows[workflow_id] = self._copy_workflow(updated)
        return self._copy_workflow(updated)

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
        if workflow_id is None:
            if workflow_key is not None and self._workflow_key_exists(workflow_key):
                raise KeyError(workflow_key)
            workflow = self.create(
                name=name,
                description=description,
                definition=definition,
                actor=actor,
                workspace_id=workspace_id,
            )
            if workflow_key is not None:
                workflow.workflow_key = workflow_key
                self._workflows[workflow.id] = self._copy_workflow(workflow)
            return workflow

        existing = self.get(workflow_id, workspace_id=workspace_id)
        if existing is None:
            raise KeyError(workflow_id)
        if workflow_key is not None and existing.workflow_key != workflow_key:
            raise KeyError(workflow_id)
        if base_version is None or base_version != existing.latest_version:
            raise WorkflowVersionConflictError(
                workflow_id=existing.id,
                workflow_key=existing.workflow_key,
                base_version=base_version or 0,
                latest_version=existing.latest_version,
                current_name=existing.name,
                last_saved_by=existing.last_saved_by,
                updated_at=existing.updated_at,
            )

        updated = existing.model_copy(deep=True)
        updated.name = name if name is not None else updated.name
        updated.description = description if description is not None else updated.description
        updated.definition = definition
        updated.latest_version += 1
        updated.updated_at = datetime.now(timezone.utc)
        if actor is not None:
            updated.last_saved_by = actor
        updated.versions.append(
            WorkflowVersionSnapshot(
                version=updated.latest_version,
                status="saved",
                name=updated.name,
                description=updated.description,
                definition=definition.model_copy(deep=True),
                created_at=updated.updated_at,
                created_by=actor,
            )
        )
        self._workflows[workflow_id] = self._copy_workflow(updated)
        return self._copy_workflow(updated)

    def publish(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> WorkflowVersionSnapshot | None:
        existing = self.get(workflow_id, workspace_id=workspace_id)
        if existing is None:
            return None

        now = datetime.now(timezone.utc)
        updated = existing.model_copy(deep=True)
        updated.published_version = existing.latest_version
        updated.updated_at = now
        snapshot = next(
            (item for item in updated.versions if item.version == existing.latest_version),
            None,
        )
        if snapshot is None:
            snapshot = WorkflowVersionSnapshot(
                version=existing.latest_version,
                name=existing.name,
                description=existing.description,
                definition=existing.definition.model_copy(deep=True),
                created_at=now,
                created_by=existing.last_saved_by,
            )
            updated.versions.append(snapshot)
        snapshot.status = "published"
        self._workflows[workflow_id] = self._copy_workflow(updated)
        return self._copy_snapshot(snapshot)

    def restore(
        self,
        workflow_id: str,
        *,
        version: int,
        actor: WorkflowActor | None = None,
        workspace_id: str | None = None,
    ) -> Workflow | None:
        _require_workspace_filter(workspace_id)
        resolved_id = self._resolve_workflow_id(workflow_id, workspace_id=workspace_id)
        if resolved_id is None:
            return None
        existing = self._workflows.get(resolved_id)
        if existing is None:
            return None

        snapshot = next((item for item in existing.versions if item.version == version), None)
        if snapshot is None:
            return None

        updated = existing.model_copy(deep=True)
        updated.name = snapshot.name
        updated.description = snapshot.description
        updated.definition = snapshot.definition.model_copy(deep=True)
        updated.updated_at = datetime.now(timezone.utc)
        updated.latest_version += 1
        if actor is not None:
            updated.last_saved_by = actor
        updated.versions.append(
            WorkflowVersionSnapshot(
                version=updated.latest_version,
                status="saved",
                name=updated.name,
                description=updated.description,
                definition=updated.definition.model_copy(deep=True),
                created_at=updated.updated_at,
                created_by=actor,
            )
        )
        self._workflows[resolved_id] = self._copy_workflow(updated)
        return self._copy_workflow(updated)

    def list_versions(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> builtins.list[WorkflowVersionSnapshot]:
        _require_workspace_filter(workspace_id)
        resolved_id = self._resolve_workflow_id(workflow_id, workspace_id=workspace_id)
        if resolved_id is None:
            return []
        workflow = self._workflows.get(resolved_id)
        if workflow is None:
            return []
        return [item.model_copy(deep=True) for item in reversed(workflow.versions)]

    def get_version(
        self,
        workflow_id: str,
        version: int,
        *,
        workspace_id: str | None = None,
    ) -> WorkflowVersionSnapshot | None:
        versions = self.list_versions(workflow_id, workspace_id=workspace_id)
        return next((item for item in versions if item.version == version), None)

    def find_duplicate_dag_hash(
        self,
        workflow_id: str,
        dag_hash: str,
        *,
        workspace_id: str | None = None,
    ) -> int | None:
        for snapshot in self.list_versions(workflow_id, workspace_id=workspace_id):
            if snapshot.dag_hash == dag_hash:
                return snapshot.version
        return None

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
        _require_workspace_filter(workspace_id)
        workflow_id = f"wf_{uuid4()}"
        now = datetime.now(timezone.utc)
        workflow = Workflow(
            id=workflow_id,
            workflow_key=self._generate_workflow_key(),
            workspace_id=workspace_id,
            name=name,
            description=description,
            definition=definition.model_copy(deep=True),
            created_at=now,
            updated_at=now,
            latest_version=1,
            published_version=1,
            created_by=actor,
            last_saved_by=actor,
            versions=[
                WorkflowVersionSnapshot(
                    version=1,
                    status="published",
                    name=name,
                    description=description,
                    definition=definition.model_copy(deep=True),
                    dag_hash=dag_hash,
                    created_at=now,
                    created_by=actor,
                )
            ],
        )
        self._workflows[workflow_id] = self._copy_workflow(workflow)
        return self._copy_workflow(workflow)

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
        existing = self.get(workflow_id, workspace_id=workspace_id)
        if existing is None:
            raise KeyError(workflow_id)
        if base_version is None or base_version != existing.latest_version:
            raise WorkflowVersionConflictError(
                workflow_id=existing.id,
                workflow_key=existing.workflow_key,
                base_version=base_version or 0,
                latest_version=existing.latest_version,
                current_name=existing.name,
                last_saved_by=existing.last_saved_by,
                updated_at=existing.updated_at,
            )

        updated = existing.model_copy(deep=True)
        updated.name = name if name is not None else updated.name
        updated.description = description if description is not None else updated.description
        updated.definition = definition.model_copy(deep=True)
        updated.latest_version += 1
        updated.published_version = updated.latest_version
        updated.updated_at = datetime.now(timezone.utc)
        if actor is not None:
            updated.last_saved_by = actor
        updated.versions.append(
            WorkflowVersionSnapshot(
                version=updated.latest_version,
                status="published",
                name=updated.name,
                description=updated.description,
                definition=definition.model_copy(deep=True),
                dag_hash=dag_hash,
                created_at=updated.updated_at,
                created_by=actor,
            )
        )
        self._workflows[workflow_id] = self._copy_workflow(updated)
        return self._copy_workflow(updated)

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    @classmethod
    def _definition_hash(cls, definition: WorkflowDefinition) -> str:
        return hashlib.sha256(
            cls._canonical_json(definition.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()

    def delete(self, workflow_id: str, *, workspace_id: str | None = None) -> bool:
        _require_workspace_filter(workspace_id)
        resolved_id = self._resolve_workflow_id(workflow_id, workspace_id=workspace_id)
        if resolved_id is None:
            return False
        del self._workflows[resolved_id]
        return True

    def deletion_impact(
        self,
        workflow_id: str,
        *,
        workspace_id: str | None = None,
    ) -> WorkflowDeletionImpact | None:
        _require_workspace_filter(workspace_id)
        resolved_id = self._resolve_workflow_id(workflow_id, workspace_id=workspace_id)
        if resolved_id is None:
            return None
        return WorkflowDeletionImpact(workflow_id=resolved_id)

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

        if sort_by not in {"updated_at", "created_at", "name"}:
            sort_by = "updated_at"

        reverse = sort_order.lower() != "asc"

        workflows = self.list(workspace_id=workspace_id)
        normalized_query = (query or "").strip().lower()

        if normalized_query:
            workflows = [
                workflow
                for workflow in workflows
                if normalized_query in (workflow.name or "").lower()
                or normalized_query in (workflow.description or "").lower()
            ]

        if sort_by == "name":
            workflows.sort(key=lambda item: item.name or "", reverse=reverse)
        elif sort_by == "created_at":
            workflows.sort(key=lambda item: item.created_at, reverse=reverse)
        else:
            workflows.sort(key=lambda item: item.updated_at, reverse=reverse)

        total = len(workflows)
        start = (safe_page - 1) * safe_limit
        end = start + safe_limit
        return workflows[start:end], total

    def _resolve_workflow_id(
        self,
        workflow_identifier: str,
        *,
        workspace_id: str | None = None,
    ) -> str | None:
        if workflow_identifier in self._workflows:
            if (
                workspace_id is None
                or self._workflows[workflow_identifier].workspace_id == workspace_id
            ):
                return workflow_identifier
            return None
        for workflow_id, workflow in self._workflows.items():
            if workflow.workflow_key == workflow_identifier:
                if workspace_id is None or workflow.workspace_id == workspace_id:
                    return workflow_id
                return None
        return None
