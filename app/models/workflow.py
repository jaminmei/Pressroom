from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WorkflowNode(BaseModel):
    id: str = Field(max_length=128)
    type: str = Field(max_length=128)
    config: dict[str, object] = Field(default_factory=dict)
    position: dict[str, object] | None = None


class WorkflowConnection(BaseModel):
    source: str
    target: str
    source_port: str | None = None
    target_port: str | None = None


class WorkflowDefinition(BaseModel):
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=200)
    connections: list[WorkflowConnection] = Field(default_factory=list, max_length=1000)

    def get_node(self, node_id: str) -> WorkflowNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None


class WorkflowActor(BaseModel):
    user_id: str
    email: str
    name: str | None = None


class Workflow(BaseModel):
    id: str
    workflow_key: str | None = None
    workspace_id: str | None = None
    name: str | None = None
    description: str | None = None
    definition: WorkflowDefinition
    created_at: datetime
    updated_at: datetime
    published_version: int | None = None
    latest_version: int = 0
    created_by: WorkflowActor | None = None
    last_saved_by: WorkflowActor | None = None
    versions: list["WorkflowVersionSnapshot"] = Field(default_factory=list)


class WorkflowVersionSnapshot(BaseModel):
    version: int
    status: Literal["saved", "published"] = "saved"
    name: str | None = None
    description: str | None = None
    definition: WorkflowDefinition
    dag_hash: str | None = None
    created_at: datetime
    created_by: WorkflowActor | None = None
