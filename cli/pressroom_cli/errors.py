from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CliError(Exception):
    message: str
    exit_code: int
    code: str
    details: Any = None
    request_id: str | None = None

    def __str__(self) -> str:
        return self.message


USAGE = 2
AUTH = 3
FORBIDDEN = 4
NOT_FOUND = 5
CONFLICT = 6
VALIDATION = 7
LOCAL = 8
TIMEOUT = 9
NETWORK = 10
REMOTE = 11
PARTIAL = 12


def http_exit_code(status: int) -> int:
    if status == 401:
        return AUTH
    if status == 403:
        return FORBIDDEN
    if status == 404:
        return NOT_FOUND
    if status == 409:
        return CONFLICT
    if status == 422 or status == 400:
        return VALIDATION
    if status >= 500:
        return REMOTE
    return REMOTE
