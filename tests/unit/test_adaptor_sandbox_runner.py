from __future__ import annotations

import base64
import socket
from pathlib import Path

import pytest

from sandbox_protocol.models import POLICY_DIGEST, ErrorKind, SandboxLimits, SandboxRequest


def _request(code: str) -> SandboxRequest:
    return SandboxRequest(
        request_id="req-1",
        code=code,
        inputs={},
        limits=SandboxLimits(),
        policy_digest=POLICY_DIGEST,
    )


def test_ast_policy_accepts_single_main_and_rejects_forbidden_nodes() -> None:
    from engines.adaptor_sandbox.runner.supervisor import AstPolicyError, validate_user_code

    validate_user_code("SAFE", _request("def main(inputs):\n    return {'text': 'ok'}"))

    for forbidden in (
        "import os\n\ndef main(inputs):\n    return {'text': 'ok'}",
        "class X: ...\n\ndef main(inputs):\n    return {'text': 'ok'}",
        "async def main(inputs):\n    return {'text': 'ok'}",
        (
            "def helper():\n    return 1\n\ndef main(inputs):\n"
            "    return {'text': open('/tmp/x').read()}"
        ),
        "def __magic__(inputs):\n    return {}\n\ndef main(inputs):\n    return {'text': 'ok'}",
    ):
        with pytest.raises(AstPolicyError):
            validate_user_code("BAD", _request(forbidden))


def test_image_crop_returns_a_valid_bounded_png_item() -> None:
    from engines.adaptor_sandbox.runner.child_entrypoint import image_crop

    # A single transparent RGBA PNG pixel.
    source = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII="
    )
    result = image_crop({"data": source, "mime_type": "image/png"}, [0, 0, 1, 1])

    assert result["mime_type"] == "image/png"
    assert result["size_bytes"] == len(base64.b64decode(result["data"]))
    assert result["dimensions"] == {"width": 1, "height": 1}


def test_cleanup_socket_path_unlinks_only_real_socket(tmp_path: Path) -> None:
    from engines.adaptor_sandbox.runner.supervisor import SocketPathError, cleanup_stale_socket

    socket_path = tmp_path / "runner.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(socket_path))
        cleanup_stale_socket(socket_path)
        assert not socket_path.exists()
    finally:
        sock.close()

    regular_file = tmp_path / "not-a-socket"
    regular_file.write_text("x", encoding="utf-8")
    with pytest.raises(SocketPathError):
        cleanup_stale_socket(regular_file)

    symlink_path = tmp_path / "symlink.sock"
    symlink_path.symlink_to(regular_file)
    with pytest.raises(SocketPathError):
        cleanup_stale_socket(symlink_path)


def test_execute_request_returns_sanitized_timeout_error() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    supervisor._approved_limits = SandboxLimits(wall_timeout_ms=100)
    response = supervisor.execute_request(
        SandboxRequest(
            request_id="req-timeout",
            code="def main(inputs):\n    while True:\n        pass",
            inputs={},
            limits=SandboxLimits(wall_timeout_ms=100),
            policy_digest=POLICY_DIGEST,
        )
    )

    assert response.status.value == "error"
    assert response.error is not None
    assert response.error.kind == ErrorKind.TIMEOUT
    assert "while True" not in response.error.message


def test_execute_request_rejects_policy_digest_mismatch() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    response = supervisor.execute_request(
        SandboxRequest(
            request_id="req-digest",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(),
            policy_digest="0" * 64,
        )
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.PROTOCOL


def test_execute_request_rejects_limits_that_do_not_match_approved_policy() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    response = supervisor.execute_request(
        SandboxRequest(
            request_id="req-limits",
            code="def main(inputs):\n    return {'text': 'ok'}",
            inputs={},
            limits=SandboxLimits(max_cpu_seconds=9),
            policy_digest=POLICY_DIGEST,
        )
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.PROTOCOL


def test_execute_request_enforces_single_flight() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    supervisor._execution_lock.acquire()
    response = supervisor.execute_request(_request("def main(inputs):\n    return {'text': 'ok'}"))
    supervisor._execution_lock.release()
    assert response.error is not None
    assert response.error.kind == ErrorKind.QUEUE_FULL


def test_execute_request_accepts_strict_node_output_shape() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    ok = supervisor.execute_request(
        _request(
            "def main(inputs):\n"
            "    return {'text': 'ok', 'binary': [], 'structured': {'x': 1}, 'metadata': {}}"
        )
    )
    assert ok.status.value == "ok"
    assert ok.result is not None
    assert ok.result.text == "ok"

    bad = supervisor.execute_request(
        _request("def main(inputs):\n    return {'text': 'ok', 'extra': True}")
    )
    assert bad.error is not None
    assert bad.error.kind == ErrorKind.RUNTIME


def test_execute_request_rejects_f_string_and_formatted_value_constructs() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    response = supervisor.execute_request(
        _request(
            "def main(inputs):\n"
            "    value = 'x'\n"
            "    return {'text': f'{value}', 'binary': [], 'structured': None, 'metadata': {}}"
        )
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.CODE


def test_execute_request_rejects_oversized_output_text() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    supervisor._approved_limits = SandboxLimits(max_output_text_bytes=4)
    response = supervisor.execute_request(
        SandboxRequest(
            request_id="req-text-cap",
            code=(
                "def main(inputs):\n"
                "    return {'text': 'hello', 'binary': [], 'structured': None, 'metadata': {}}"
            ),
            inputs={},
            limits=SandboxLimits(max_output_text_bytes=4),
            policy_digest=POLICY_DIGEST,
        )
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.RESOURCE
    assert response.error.message == "resource limit exceeded"


def test_execute_request_rejects_oversized_output_structured() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    supervisor._approved_limits = SandboxLimits(max_output_structured_bytes=8)
    response = supervisor.execute_request(
        SandboxRequest(
            request_id="req-structured-cap",
            code=(
                "def main(inputs):\n"
                "    return {'text': None, 'binary': [], 'structured': {'long': 'payload'}, "
                "'metadata': {}}"
            ),
            inputs={},
            limits=SandboxLimits(max_output_structured_bytes=8),
            policy_digest=POLICY_DIGEST,
        )
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.RESOURCE
    assert response.error.message == "resource limit exceeded"


def test_execute_request_rejects_oversized_output_binary() -> None:
    from engines.adaptor_sandbox.runner.supervisor import RunnerSupervisor

    supervisor = RunnerSupervisor(socket_dir=Path("/tmp"))
    supervisor._approved_limits = SandboxLimits(max_output_binary_bytes=4)
    response = supervisor.execute_request(
        SandboxRequest(
            request_id="req-binary-cap",
            code=(
                "def main(inputs):\n"
                "    return {'text': None, 'binary': [{'data': 'aGVsbG8=', "
                "'mime_type': 'text/plain', "
                "'size_bytes': 5}], 'structured': None, 'metadata': {}}"
            ),
            inputs={},
            limits=SandboxLimits(max_output_binary_bytes=4),
            policy_digest=POLICY_DIGEST,
        )
    )

    assert response.error is not None
    assert response.error.kind == ErrorKind.RESOURCE
    assert response.error.message == "resource limit exceeded"
