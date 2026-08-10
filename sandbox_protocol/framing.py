from __future__ import annotations

import socket

from pydantic import BaseModel, ValidationError


class FrameError(ValueError):
    pass


class FrameTooLargeError(FrameError):
    pass


def encode_message(message: BaseModel, *, max_bytes: int) -> bytes:
    payload = message.model_dump_json().encode("utf-8")
    if len(payload) > max_bytes:
        raise FrameTooLargeError("frame exceeds maximum size")
    return len(payload).to_bytes(4, "big") + payload


def decode_message(frame: bytes, model_type: type[BaseModel], *, max_bytes: int) -> BaseModel:
    if len(frame) < 4:
        raise FrameError("frame missing length prefix")
    expected = int.from_bytes(frame[:4], "big")
    payload = frame[4:]
    if expected > max_bytes:
        raise FrameTooLargeError("frame exceeds maximum size")
    if expected != len(payload):
        raise FrameError("frame length mismatch or trailing bytes present")
    try:
        return model_type.model_validate_json(payload)
    except ValidationError as exc:
        raise FrameError("frame payload is invalid") from exc


def recv_frame(sock: socket.socket, *, max_bytes: int) -> bytes:
    prefix = _recv_exact(sock, 4)
    if prefix is None:
        raise FrameError("frame missing length prefix")
    expected = int.from_bytes(prefix, "big")
    if expected > max_bytes:
        raise FrameTooLargeError("frame exceeds maximum size")
    payload = _recv_exact(sock, expected)
    if payload is None:
        raise FrameError("incomplete frame payload")
    return prefix + payload


def send_frame(sock: socket.socket, message: BaseModel, *, max_bytes: int) -> None:
    sock.sendall(encode_message(message, max_bytes=max_bytes))


def _recv_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)
