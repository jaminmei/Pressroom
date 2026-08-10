from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrustedIterationScope:
    owner_node_id: str
    item: Any
    index: int
