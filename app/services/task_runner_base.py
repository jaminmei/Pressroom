from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.task import TaskContext
from app.services.topological_sort import ExecutionPlan


class TaskRunnerBase(ABC):
    @abstractmethod
    async def run(self, plan: ExecutionPlan, context: TaskContext) -> None:
        """Run workflow nodes according to the provided plan."""

    async def execute_plan(self, plan: ExecutionPlan, context: TaskContext) -> None:
        """Backward-compatible alias for legacy callers."""
        await self.run(plan, context)

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """Attempt to cancel a running task."""
