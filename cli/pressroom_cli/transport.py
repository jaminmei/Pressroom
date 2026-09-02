from __future__ import annotations

import json
import mimetypes
import socket
import ssl
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pressroom_cli.context import ExecutorContext
from pressroom_cli.errors import NETWORK, TIMEOUT, CliError, http_exit_code


@dataclass(frozen=True, slots=True)
class ApiResponse:
    data: Any
    status: int
    request_id: str | None
    content_type: str
    raw: bytes | None = None


class ApiClient:
    def __init__(self, context: ExecutorContext, *, timeout: float = 30.0) -> None:
        self.context = context
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: Any = None,
        encoded_body: bytes | None = None,
        content_type: str | None = None,
    ) -> ApiResponse:
        if not path.startswith("/api/"):
            raise CliError("API path must start with /api/", NETWORK, "INVALID_API_PATH")
        url = f"{self.context.host}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request_id = str(uuid.uuid4())
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.context.token_provider.current_token()}",
            "X-Agent-Session-Id": self.context.agent_session_id,
            "X-Request-Id": request_id,
            "X-Workspace-Id": self.context.workspace_id,
        }
        encoded = encoded_body
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type is not None:
            headers["Content-Type"] = content_type
        request = Request(url, data=encoded, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                content = response.read()
                content_type = response.headers.get_content_type()
                response_request_id = response.headers.get("X-Request-Id") or request_id
                return ApiResponse(
                    data=self._decode(content, content_type),
                    status=response.status,
                    request_id=response_request_id,
                    content_type=content_type,
                    raw=content if content_type != "application/json" else None,
                )
        except HTTPError as exc:
            raw = exc.read()
            content_type = exc.headers.get_content_type() if exc.headers else "application/json"
            payload = self._decode(raw, content_type)
            code, message, details = self._error_fields(payload, exc.code)
            raise CliError(
                message,
                http_exit_code(exc.code),
                code,
                details,
                exc.headers.get("X-Request-Id") if exc.headers else request_id,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise CliError(
                "Request timed out", TIMEOUT, "REQUEST_TIMEOUT", request_id=request_id
            ) from exc
        except (URLError, ssl.SSLError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            safe_reason = type(reason).__name__ if reason else type(exc).__name__
            raise CliError(
                f"Could not connect to platform ({safe_reason})",
                NETWORK,
                "NETWORK_ERROR",
                request_id=request_id,
            ) from exc

    def multipart_request(
        self,
        method: str,
        path: str,
        *,
        files: Iterable[tuple[str, str]],
        fields: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        boundary = f"pressroom-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in (fields or {}).items():
            safe_name = name.replace('"', "")
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{safe_name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        for field_name, source_path in files:
            source = self.context.authorize_file_path(source_path)
            if not source.is_file():
                raise CliError(
                    f"Upload file does not exist: {source}",
                    8,
                    "LOCAL_FILE_NOT_FOUND",
                )
            try:
                content = source.read_bytes()
            except OSError as exc:
                raise CliError("Could not read upload file", 8, "LOCAL_FILE_READ_FAILED") from exc
            mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            safe_field = field_name.replace('"', "")
            safe_filename = source.name.replace('"', "")
            chunks.extend(
                [
                    (
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="{safe_field}"; '
                        f'filename="{safe_filename}"\r\n'
                        f"Content-Type: {mime_type}\r\n\r\n"
                    ).encode("utf-8"),
                    content,
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("ascii"))
        return self.request(
            method,
            path,
            encoded_body=b"".join(chunks),
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def upload_file(self, path: str, *, field_name: str = "file") -> ApiResponse:
        return self.multipart_request(
            "POST",
            "/api/files",
            files=[(field_name, path)],
        )

    @staticmethod
    def _decode(content: bytes, content_type: str) -> Any:
        if not content:
            return None
        if content_type == "application/json" or content.lstrip().startswith((b"{", b"[")):
            try:
                return json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {"message": "Platform returned invalid JSON"}
        return {"content_type": content_type, "size": len(content)}

    @staticmethod
    def _error_fields(payload: Any, status: int) -> tuple[str, str, Any]:
        if isinstance(payload, dict):
            nested = payload.get("error")
            if isinstance(nested, dict):
                return (
                    str(nested.get("code") or f"HTTP_{status}"),
                    str(nested.get("message") or "Platform request failed"),
                    nested.get("details"),
                )
            return (
                str(payload.get("error_code") or f"HTTP_{status}"),
                str(payload.get("message") or payload.get("detail") or "Platform request failed"),
                payload.get("details"),
            )
        return f"HTTP_{status}", "Platform request failed", None
