from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TextIO

from pressroom_cli.errors import LOCAL, USAGE, CliError


def load_json_input(source: str, stdin: TextIO) -> Any:
    try:
        text = stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError("Could not read JSON input", LOCAL, "INPUT_READ_FAILED") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(
            f"JSON input is invalid at line {exc.lineno}, column {exc.colno}",
            USAGE,
            "INVALID_JSON_INPUT",
        ) from exc


def write_binary_atomic(
    output_path: str,
    content: bytes,
    *,
    force: bool,
) -> Path:
    output = Path(output_path).expanduser()
    if output.exists() and not force:
        raise CliError(
            "Output already exists; use --force to replace it",
            LOCAL,
            "OUTPUT_EXISTS",
        )
    if not output.parent.exists():
        raise CliError("Output directory does not exist", LOCAL, "OUTPUT_DIRECTORY_NOT_FOUND")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, output)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CliError("Could not write output file", LOCAL, "OUTPUT_WRITE_FAILED") from exc
    return output
