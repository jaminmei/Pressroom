"""Static privacy invariants for Python engine logs."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_ROOT = _REPO_ROOT / "engines"
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_SENSITIVE_DYNAMIC_NAMES = {
    "authorization",
    "base_url",
    "block",
    "content",
    "credential",
    "document",
    "endpoint",
    "file_path",
    "image_path",
    "line",
    "mapping_path",
    "path",
    "path_to_process",
    "payload",
    "prompt",
    "ref",
    "request",
    "response",
    "result",
    "secret",
    "source_path",
    "temp_path",
    "url",
}


def _engine_sources() -> list[Path]:
    return [
        path
        for path in sorted(_ENGINE_ROOT.rglob("*.py"))
        if "tests" not in path.relative_to(_ENGINE_ROOT).parts
    ]


def _logger_call(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
        return None
    return node if node.func.attr in _LOG_METHODS else None


def _sensitive_references(node: ast.AST) -> set[str]:
    """Find raw sensitive values while allowing aggregate-only logging via len/type."""
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, call: ast.Call) -> None:
            if isinstance(call.func, ast.Name) and call.func.id in {"len", "type"}:
                return
            self.generic_visit(call)

        def visit_Name(self, name: ast.Name) -> None:
            if name.id.lower() in _SENSITIVE_DYNAMIC_NAMES:
                found.add(name.id)

        def visit_Attribute(self, attribute: ast.Attribute) -> None:
            if attribute.attr.lower() in _SENSITIVE_DYNAMIC_NAMES:
                found.add(attribute.attr)
            self.generic_visit(attribute)

    Visitor().visit(node)
    return found


def _has_error_type(call: ast.Call, exception_name: str) -> bool:
    has_label = any(
        isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "error_type=" in arg.value
        for arg in call.args
    )
    has_exception_type = any(
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == exception_name
        for node in ast.walk(call)
    )
    return has_label and has_exception_type


def _nearest_exception_handler(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> ast.ExceptHandler | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.ExceptHandler):
            return current
        current = parents.get(current)
    return None


def test_engine_logs_never_emit_sensitive_values_or_tracebacks() -> None:
    violations: list[str] = []

    for path in _engine_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(_REPO_ROOT)
        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            call = _logger_call(node)
            if call is None:
                continue
            method = call.func.attr
            if method == "exception":
                violations.append(f"{relative}:{call.lineno}: logger.exception is forbidden")
            if any(keyword.arg == "exc_info" for keyword in call.keywords):
                violations.append(f"{relative}:{call.lineno}: exc_info is forbidden")
            sensitive = _sensitive_references(call)
            if sensitive:
                violations.append(
                    f"{relative}:{call.lineno}: sensitive log arguments {sorted(sensitive)}"
                )
            handler = _nearest_exception_handler(call, parents)
            if handler is not None and handler.name and not _has_error_type(call, handler.name):
                violations.append(
                    f"{relative}:{call.lineno}: exception log must contain sanitized error_type"
                )

    assert not violations, "\n".join(violations)
