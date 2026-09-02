from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api.auth import require_workspace_capability
from app.models.execution import NodeOutput
from app.services.adaptor_workbench import execute_adaptor_workbench
from app.services.workspace_access import ResolvedContext

router = APIRouter(prefix="/adaptor-workbench", tags=["adaptor-workbench"])

WorkflowEditDraftContext = Annotated[
    ResolvedContext, Depends(require_workspace_capability("workflow.edit_draft"))
]
WorkflowRunContext = Annotated[
    ResolvedContext, Depends(require_workspace_capability("workflow.run"))
]


class AdaptorWorkbenchExecuteRequest(BaseModel):
    code: str = Field(max_length=100_000)
    inputs: dict[str, NodeOutput] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be blank")
        return value


@router.post("/execute")
async def execute_adaptor_workbench_request(
    payload: AdaptorWorkbenchExecuteRequest,
    _edit_ctx: WorkflowEditDraftContext,
    _run_ctx: WorkflowRunContext,
) -> dict[str, object]:
    output = await execute_adaptor_workbench(code=payload.code, inputs=payload.inputs)
    return {"success": True, "data": {"output": output.model_dump(mode="json")}}
