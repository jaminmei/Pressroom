from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from pressroom_cli.errors import AUTH, LOCAL, CliError

_MAX_TOKEN_BYTES = 16_384


class TokenProvider(Protocol):
    def current_token(self) -> str: ...


@dataclass(frozen=True, slots=True)
class FileTokenProvider:
    path: Path

    def current_token(self) -> str:
        try:
            if not self.path.is_absolute() or not self.path.is_file():
                raise OSError
            if self.path.stat().st_size > _MAX_TOKEN_BYTES:
                raise CliError(
                    "Agent Session token file is too large",
                    AUTH,
                    "AGENT_SESSION_TOKEN_INVALID",
                )
            token = self.path.read_text(encoding="utf-8").strip()
        except CliError:
            raise
        except (OSError, UnicodeError) as exc:
            raise CliError(
                "Agent Session token is unavailable",
                AUTH,
                "AGENT_SESSION_TOKEN_UNAVAILABLE",
            ) from exc
        if not token or any(character.isspace() for character in token):
            raise CliError(
                "Agent Session token is invalid",
                AUTH,
                "AGENT_SESSION_TOKEN_INVALID",
            )
        return token


@dataclass(frozen=True, slots=True)
class StaticTokenProvider:
    """In-memory provider for isolated Tool Executor tests only."""

    token: str

    def current_token(self) -> str:
        if not self.token or any(character.isspace() for character in self.token):
            raise CliError(
                "Agent Session token is invalid",
                AUTH,
                "AGENT_SESSION_TOKEN_INVALID",
            )
        return self.token


@dataclass(frozen=True, slots=True)
class ExecutorContext:
    host: str
    workspace_id: str
    agent_session_id: str
    token_provider: TokenProvider
    allowed_file_roots: tuple[Path, ...] = ()

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> ExecutorContext:
        env = environment if environment is not None else os.environ
        required = {
            "PRESSROOM_HOST": env.get("PRESSROOM_HOST", ""),
            "PRESSROOM_WORKSPACE_ID": env.get("PRESSROOM_WORKSPACE_ID", ""),
            "PRESSROOM_AGENT_SESSION_ID": env.get("PRESSROOM_AGENT_SESSION_ID", ""),
            "PRESSROOM_TOKEN_FILE": env.get("PRESSROOM_TOKEN_FILE", ""),
        }
        missing = sorted(name for name, value in required.items() if not value.strip())
        if missing:
            raise CliError(
                "Tool Executor context is incomplete",
                LOCAL,
                "MANAGED_CONTEXT_MISSING",
                {"missing": missing},
            )
        workspace_id = _identifier(required["PRESSROOM_WORKSPACE_ID"], "workspace")
        agent_session_id = _identifier(required["PRESSROOM_AGENT_SESSION_ID"], "Agent Session")
        roots_value = env.get("PRESSROOM_ALLOWED_FILE_ROOTS", "")
        roots = tuple(
            Path(item).expanduser().resolve()
            for item in roots_value.split(os.pathsep)
            if item.strip()
        )
        return cls(
            host=_normalize_host(
                required["PRESSROOM_HOST"],
                allow_insecure_http=_true(env.get("PRESSROOM_ALLOW_INSECURE_HTTP")),
            ),
            workspace_id=workspace_id,
            agent_session_id=agent_session_id,
            token_provider=FileTokenProvider(Path(required["PRESSROOM_TOKEN_FILE"])),
            allowed_file_roots=roots,
        )

    def authorize_file_path(self, value: str | Path) -> Path:
        candidate = Path(value).expanduser().resolve()
        if not self.allowed_file_roots or not any(
            candidate == root or candidate.is_relative_to(root) for root in self.allowed_file_roots
        ):
            raise CliError(
                "File path is outside the Agent Session allowlist",
                LOCAL,
                "FILE_ACCESS_NOT_AUTHORIZED",
            )
        return candidate


def _identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise CliError(
            f"Managed {label} identifier is invalid",
            LOCAL,
            "MANAGED_CONTEXT_INVALID",
        )
    return normalized


def _normalize_host(value: str, *, allow_insecure_http: bool) -> str:
    raw = value.strip().rstrip("/")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.path not in {"", "/"}:
        raise CliError(
            "Managed host must be an HTTP(S) origin without a path",
            LOCAL,
            "MANAGED_CONTEXT_INVALID",
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise CliError(
            "Managed host must not include credentials, query, or fragment",
            LOCAL,
            "MANAGED_CONTEXT_INVALID",
        )
    if parts.scheme == "http" and not allow_insecure_http:
        raise CliError(
            "Managed plain HTTP requires PRESSROOM_ALLOW_INSECURE_HTTP=true",
            LOCAL,
            "MANAGED_CONTEXT_INVALID",
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise CliError(
            "Managed host has an invalid port",
            LOCAL,
            "MANAGED_CONTEXT_INVALID",
        ) from exc
    hostname = parts.hostname
    netloc = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def _true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
