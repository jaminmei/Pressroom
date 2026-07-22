"""Static privacy guard for application logging."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "app"
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
SENSITIVE_FIELDS = {
    "authorization",
    "base_url",
    "body",
    "content",
    "db_path",
    "endpoint",
    "file_path",
    "input_file_path",
    "path",
    "prompt",
    "response",
    "secret",
    "storage_path",
    "temp_path",
    "tmp_path",
    "url",
}
SENSITIVE_FORMAT_FIELD = re.compile(
    r"(?:authorization|base_url|body|content|endpoint|path|prompt|response|secret|url)\s*=",
    re.IGNORECASE,
)


def _is_logger_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in LOG_METHODS:
        return False
    owner = node.func.value
    return isinstance(owner, ast.Name) and (
        owner.id in {"log", "logger", "logging"} or owner.id.lower().endswith("logger")
    )


def _is_error_type_expression(node: ast.AST, exception_name: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == exception_name
    )


def _uses_raw_exception(node: ast.AST, exception_name: str) -> bool:
    if _is_error_type_expression(node, exception_name):
        return False
    if isinstance(node, ast.Name) and node.id == exception_name:
        return True
    return any(_uses_raw_exception(child, exception_name) for child in ast.iter_child_nodes(node))


def _sensitive_argument_fields(node: ast.AST) -> set[str]:
    fields: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id.lower() in SENSITIVE_FIELDS:
            fields.add(child.id)
        elif isinstance(child, ast.Attribute) and child.attr.lower() in SENSITIVE_FIELDS:
            fields.add(child.attr)
    return fields


class _LoggingPrivacyVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.exception_names: list[str] = []
        self.violations: list[str] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        if node.name is not None:
            self.exception_names.append(node.name)
        for statement in node.body:
            self.visit(statement)
        if node.name is not None:
            self.exception_names.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not _is_logger_call(node):
            self.generic_visit(node)
            return

        assert isinstance(node.func, ast.Attribute)
        location = f"{self.path.relative_to(ROOT)}:{node.lineno}"
        if node.func.attr == "exception":
            self.violations.append(f"{location}: logger.exception exposes a traceback")
        if any(keyword.arg == "exc_info" for keyword in node.keywords):
            self.violations.append(f"{location}: exc_info exposes a traceback")

        message = node.args[0] if node.args else None
        if isinstance(message, ast.Constant) and isinstance(message.value, str):
            if SENSITIVE_FORMAT_FIELD.search(message.value):
                self.violations.append(f"{location}: sensitive field appears in log format")

        value_nodes = [*node.args[1:], *(keyword.value for keyword in node.keywords)]
        for value in value_nodes:
            fields = _sensitive_argument_fields(value)
            if fields:
                joined = ", ".join(sorted(fields))
                self.violations.append(f"{location}: sensitive log argument(s): {joined}")
            for exception_name in self.exception_names:
                if _uses_raw_exception(value, exception_name):
                    self.violations.append(
                        f"{location}: raw exception {exception_name!r} passed to logger"
                    )

        self.generic_visit(node)


def test_application_logging_excludes_sensitive_values_and_tracebacks() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        visitor = _LoggingPrivacyVisitor(path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        violations.extend(visitor.violations)

    assert not violations, "Logging privacy violations:\n" + "\n".join(violations)
