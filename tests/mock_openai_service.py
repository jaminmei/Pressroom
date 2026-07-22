#!/usr/bin/env python3
"""Small dependency-free OpenAI/Azure-compatible server for public E2E tests."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_REQUESTS: list[dict[str, object]] = []
_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "DocConvMock/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"status": "healthy"})
            return
        if parsed.path in {"/v1/models", "/models"}:
            self._json(
                HTTPStatus.OK,
                {"object": "list", "data": [{"id": "mock-vision", "object": "model"}]},
            )
            return
        if parsed.path == "/requests":
            with _LOCK:
                snapshot = list(_REQUESTS)
            self._json(HTTPStatus.OK, {"requests": snapshot})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_DELETE(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/requests":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        with _LOCK:
            _REQUESTS.clear()
        self._json(HTTPStatus.OK, {"deleted": True})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not (
            parsed.path in {"/v1/chat/completions", "/chat/completions"}
            or (
                parsed.path.startswith("/azure/openai/deployments/")
                and parsed.path.endswith("/chat/completions")
            )
        ):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        has_image = any(
            isinstance(content, dict) and content.get("type") == "image_url"
            for message in messages
            if isinstance(message, dict)
            for content in (
                message.get("content", []) if isinstance(message.get("content"), list) else []
            )
        )
        authorization = self.headers.get("Authorization", "")
        auth_scheme = authorization.partition(" ")[0].lower() if authorization else None
        record = {
            "path": parsed.path,
            "model": payload.get("model") if isinstance(payload, dict) else None,
            "has_image": has_image,
            "auth_scheme": auth_scheme,
            "has_api_key_header": bool(self.headers.get("api-key")),
            "api_version": parse_qs(parsed.query).get("api-version", [None])[0],
        }
        with _LOCK:
            _REQUESTS.append(record)

        self._json(
            HTTPStatus.OK,
            {
                "id": "chatcmpl-public-mock",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"result":"mock vision response"}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
        )


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
