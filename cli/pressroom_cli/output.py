from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any, TextIO

from pressroom_cli.errors import CliError


def success_envelope(data: Any, *, request_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "pressroom-envelope.v1",
        "ok": True,
        "data": data,
        "error": None,
        "request_id": request_id,
    }


def error_envelope(error: CliError) -> dict[str, Any]:
    payload = asdict(error)
    payload.pop("exit_code", None)
    payload.pop("request_id", None)
    return {
        "schema_version": "pressroom-envelope.v1",
        "ok": False,
        "data": None,
        "error": payload,
        "request_id": error.request_id,
    }


def emit_json(value: Any, *, stream: TextIO = sys.stdout) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    stream.write("\n")


def emit_human(value: Any, *, stream: TextIO = sys.stdout) -> None:
    if isinstance(value, str):
        stream.write(f"{value}\n")
        return
    stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    stream.write("\n")
