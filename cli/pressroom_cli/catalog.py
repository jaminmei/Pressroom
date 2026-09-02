from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml

from pressroom_cli.errors import LOCAL, CliError


def load_catalog() -> dict[str, Any]:
    resource = files("pressroom_cli").joinpath("tool-catalog.yaml")
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CliError("Installed command catalog is invalid", LOCAL, "CATALOG_INVALID") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("commands"), list):
        raise CliError("Installed command catalog is invalid", LOCAL, "CATALOG_INVALID")
    return payload


def executor_catalog() -> dict[str, Any]:
    """Return the business tools installed for the managed Tool Executor."""
    payload = load_catalog()
    payload = dict(payload)
    payload["commands"] = [
        command
        for command in payload["commands"]
        if command.get("status") == "cli-ready"
        and command.get("exposure") in {"agent-default", "agent-confirmation"}
    ]
    return payload
