from __future__ import annotations

import base64
import binascii
import builtins
import json
import struct
import sys
import zlib
from collections.abc import Callable, Mapping
from typing import Any, cast

_ALLOWED_BUILTINS = [
    "abs",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "range",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
]


class ResourceLimitExceeded(ValueError):
    pass


def _png_crop(data: bytes, bbox: object) -> tuple[bytes, dict[str, int]]:
    """Crop a non-interlaced 8-bit PNG using only the standard library."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("image_crop accepts PNG data only")
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("invalid PNG")
        chunks.append((kind, data[offset + 8 : offset + 8 + length]))
        offset = end
        if kind == b"IEND":
            break

    header = next((payload for kind, payload in chunks if kind == b"IHDR"), None)
    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    if header is None or len(header) != 13 or not compressed:
        raise ValueError("invalid PNG")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", header
    )
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if (
        not width
        or not height
        or bit_depth != 8
        or channels is None
        or compression != 0
        or filter_method != 0
        or interlace != 0
    ):
        raise ValueError("unsupported PNG")

    if isinstance(bbox, dict):
        if all(key in bbox for key in ("x", "y", "width", "height")):
            x, y = float(bbox["x"]), float(bbox["y"])
            right, bottom = x + float(bbox["width"]), y + float(bbox["height"])
        else:
            x, y = float(bbox["x1"]), float(bbox["y1"])
            right, bottom = float(bbox["x2"]), float(bbox["y2"])
    elif isinstance(bbox, list) and len(bbox) == 4:
        x, y, right, bottom = (float(value) for value in bbox)
    else:
        raise ValueError("invalid crop bbox")
    if max(abs(x), abs(y), abs(right), abs(bottom)) <= 1:
        x, right = x * width, right * width
        y, bottom = y * height, bottom * height
    left, top = max(0, int(x)), max(0, int(y))
    right, bottom = min(width, int(right)), min(height, int(bottom))
    if right <= left or bottom <= top:
        raise ValueError("empty crop bbox")

    stride = width * channels
    decoded = zlib.decompress(compressed)
    if len(decoded) != height * (stride + 1):
        raise ValueError("invalid PNG data")
    rows: list[bytearray] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = decoded[cursor]
        row = bytearray(decoded[cursor + 1 : cursor + 1 + stride])
        cursor += stride + 1
        for index in range(stride):
            left_byte = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left_byte) & 255
            elif filter_type == 2:
                row[index] = (row[index] + above) & 255
            elif filter_type == 3:
                row[index] = (row[index] + ((left_byte + above) // 2)) & 255
            elif filter_type == 4:
                predictor = left_byte + above - upper_left
                distances = (
                    abs(predictor - left_byte),
                    abs(predictor - above),
                    abs(predictor - upper_left),
                )
                if distances[0] <= distances[1] and distances[0] <= distances[2]:
                    nearest = left_byte
                elif distances[1] <= distances[2]:
                    nearest = above
                else:
                    nearest = upper_left
                row[index] = (row[index] + nearest) & 255
            elif filter_type != 0:
                raise ValueError("unsupported PNG filter")
        rows.append(row)
        previous = row

    raw = b"".join(
        b"\x00" + bytes(row[left * channels : right * channels]) for row in rows[top:bottom]
    )
    crop_header = struct.pack(
        ">IIBBBBB", right - left, bottom - top, bit_depth, color_type, 0, 0, 0
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", crop_header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""),
        {"width": right - left, "height": bottom - top},
    )


def image_crop(binary_item: object, bbox: object) -> dict[str, object]:
    """Return a bounded PNG crop as a sandbox-valid binary item."""
    if not isinstance(binary_item, dict) or binary_item.get("mime_type") not in {"image/png", ""}:
        raise ValueError("image_crop requires a PNG binary item")
    encoded = binary_item.get("data")
    if not isinstance(encoded, str):
        raise ValueError("image_crop requires inline binary data")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid image data") from exc
    cropped, dimensions = _png_crop(data, bbox)
    return {
        "data": base64.b64encode(cropped).decode("ascii"),
        "mime_type": "image/png",
        "size_bytes": len(cropped),
        "dimensions": dimensions,
    }


def _decode_base64_size(value: str) -> int:
    import base64

    try:
        return len(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid binary output") from exc


def _validate_result(result: object, limits: dict[str, int]) -> str:
    if not isinstance(result, dict):
        raise ValueError("invalid node output")

    allowed_keys = {"text", "binary", "structured", "metadata"}
    if set(result) - allowed_keys:
        raise ValueError("invalid node output")

    text = result.get("text")
    if text is not None:
        if not isinstance(text, str):
            raise ValueError("invalid node output")
        if len(text.encode("utf-8")) > int(limits["max_output_text_bytes"]):
            raise ResourceLimitExceeded("output text exceeds max_output_text_bytes")

    structured = result.get("structured")
    if structured is not None:
        structured_bytes = len(
            json.dumps(structured, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if structured_bytes > int(limits["max_output_structured_bytes"]):
            raise ResourceLimitExceeded("output structured exceeds max_output_structured_bytes")

    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("invalid node output")
    metadata_bytes = len(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if metadata_bytes > int(limits["max_output_structured_bytes"]):
        raise ResourceLimitExceeded("output metadata exceeds response budget")

    binary = result.get("binary", [])
    if not isinstance(binary, list):
        raise ValueError("invalid node output")
    allowed_binary_keys = {"data", "mime_type", "size_bytes", "dimensions"}
    total_binary = 0
    for item in binary:
        if not isinstance(item, dict) or set(item) - allowed_binary_keys:
            raise ValueError("invalid binary output")
        data = item.get("data")
        size_bytes = item.get("size_bytes")
        if not isinstance(data, str) or not isinstance(size_bytes, int):
            raise ValueError("invalid binary output")
        decoded_size = _decode_base64_size(data)
        if decoded_size != size_bytes:
            raise ValueError("invalid binary output")
        if decoded_size > int(limits["max_output_binary_bytes"]):
            raise ResourceLimitExceeded("output binary item exceeds max_output_binary_bytes")
        total_binary += decoded_size

    if total_binary > int(limits["max_binary_total_bytes"]):
        raise ResourceLimitExceeded("output binary total exceeds max_binary_total_bytes")

    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if len(payload.encode("utf-8")) > int(limits["max_response_bytes"]):
        raise ResourceLimitExceeded("output payload exceeds max_response_bytes")
    return payload


def _resolve_main(namespace: Mapping[str, object]) -> Callable[[dict[str, Any]], object]:
    main_func = namespace.get("main")
    if not callable(main_func):
        raise ValueError("main must be callable")
    return cast(Callable[[dict[str, Any]], object], main_func)


def main() -> None:
    request_payload = json.load(sys.stdin)
    try:
        sys.setrecursionlimit(int(request_payload["recursion_limit"]))
        limits = request_payload["limits"]
        if not isinstance(limits, dict):
            raise ValueError("invalid limits")
        namespace = {
            "__builtins__": {name: getattr(builtins, name) for name in _ALLOWED_BUILTINS},
            "image_crop": image_crop,
        }
        exec(request_payload["code"], namespace, namespace)
        main_func = _resolve_main(namespace)
        result = main_func(request_payload["inputs"])
        sys.stdout.write(_validate_result(result, limits))
    except ResourceLimitExceeded as exc:
        sys.stdout.write(
            json.dumps(
                {
                    "kind": "resource",
                    "message": "resource limit exceeded",
                },
                separators=(",", ":"),
            )
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
