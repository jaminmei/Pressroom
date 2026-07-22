from __future__ import annotations

from pathlib import Path


def ensure_path_within_root(path: str | Path, root: str | Path) -> Path:
    """Resolve a path and ensure it stays within the allowed root directory."""

    candidate = Path(path).resolve()
    root_path = Path(root).resolve()
    if not str(candidate).startswith(str(root_path) + "/") and candidate != root_path:
        raise ValueError(f"Path traversal detected: {path}")
    return candidate


def ensure_path_within_roots(path: str | Path, roots: list[str | Path]) -> Path:
    """Resolve a path and ensure it stays within at least one of the allowed root directories."""

    candidate = Path(path).resolve()
    for root in roots:
        root_path = Path(root).resolve()
        if str(candidate).startswith(str(root_path) + "/") or candidate == root_path:
            return candidate
    raise ValueError(f"Path traversal detected: {path}")
