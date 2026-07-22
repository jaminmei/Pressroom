from __future__ import annotations

import json
from typing import Any

_SCHEMA_TEMPLATES: dict[str, dict[str, Any]] = {
    "bank_transaction": {
        "name": "Bank Transaction",
        "schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "description": {"type": "string"},
                "amount": {"type": "number"},
                "currency": {"type": "string"},
            },
        },
    },
    "invoice": {
        "name": "Invoice",
        "schema": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
                "vendor": {"type": "string"},
                "total": {"type": "number"},
                "due_date": {"type": "string"},
            },
        },
    },
    "receipt": {
        "name": "Receipt",
        "schema": {
            "type": "object",
            "properties": {
                "merchant": {"type": "string"},
                "date": {"type": "string"},
                "total": {"type": "number"},
                "items": {"type": "array"},
            },
        },
    },
}


def validate_json_schema(schema_text: str) -> tuple[bool, str | None]:
    """Validate the minimal JSON Schema shape used by workflow model nodes."""
    if not schema_text.strip():
        return True, None

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON: {exc.msg}"

    if not isinstance(schema, dict):
        return False, "Schema root must be a JSON object"
    if schema.get("type") != "object":
        return False, "Schema type must be object"
    if "properties" not in schema:
        return False, "Schema must include properties"
    if not isinstance(schema["properties"], dict):
        return False, "Schema properties must be an object"

    return True, None


def get_schema_template(template_name: str) -> str | None:
    """Return a named schema template as JSON, or None when unknown."""
    template = _SCHEMA_TEMPLATES.get(template_name)
    if template is None:
        return None
    return json.dumps(template, ensure_ascii=False)
