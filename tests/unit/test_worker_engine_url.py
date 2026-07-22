from __future__ import annotations

from unittest.mock import patch

import pytest

from app.worker_tasks import _resolve_engine_url


class _FakeSettings:
    ocr_engine_url = "http://localhost:8002"
    vlm_engine_url = "http://localhost:8003"
    text_engine_url = "http://localhost:8004"
    markitdown_engine_url = "http://localhost:8005"


@pytest.mark.parametrize(
    ("engine_type", "expected"),
    [
        ("ocr", "http://localhost:8002"),
        ("vlm", "http://localhost:8003"),
        ("text", "http://localhost:8004"),
        ("markitdown", "http://localhost:8005"),
    ],
)
def test_legacy_worker_helper_is_limited_to_builtin_engines(
    engine_type: str,
    expected: str,
) -> None:
    with patch("app.worker_tasks.get_settings", return_value=_FakeSettings()):
        assert _resolve_engine_url(engine_type) == expected


def test_legacy_worker_helper_rejects_unknown_engine() -> None:
    with patch("app.worker_tasks.get_settings", return_value=_FakeSettings()):
        with pytest.raises(ValueError, match="Unsupported engine type"):
            _resolve_engine_url("unknown_engine")
