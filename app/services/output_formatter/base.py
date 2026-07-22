from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.models.execution import NodeOutput
from app.models.output import OutputResult


class FormatterContext(BaseModel):
    task_id: str
    node_id: str
    engine_node_id: str
    storage_base_path: str
    source_filename: str
    engine_chain: list[str]


class OutputFormatter(ABC):
    """Base interface for converting node output into target output formats."""

    @abstractmethod
    def format(
        self,
        document: NodeOutput,
        config: dict,
        context: FormatterContext,
    ) -> OutputResult:
        raise NotImplementedError
