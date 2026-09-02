from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pressroom_cli.context import ExecutorContext


@dataclass(frozen=True, slots=True)
class CommandResult:
    data: Any
    request_id: str | None = None
    exit_code: int = 0


@dataclass(slots=True)
class Runtime:
    context: ExecutorContext | None = None
    environment: Mapping[str, str] | None = None
    stdout: Any = sys.stdout
    stderr: Any = sys.stderr
    stdin: Any = sys.stdin

    def executor_context(self) -> ExecutorContext:
        if self.context is None:
            self.context = ExecutorContext.from_environment(self.environment)
        return self.context
