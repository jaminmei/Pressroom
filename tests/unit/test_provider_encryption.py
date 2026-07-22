from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.providers.encryption import EncryptionError, get_fernet


def test_runtime_encryption_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVIDER_ENCRYPTION_KEY", raising=False)

    with pytest.raises(EncryptionError, match="required"):
        get_fernet()


def test_explicit_encryption_key_remains_available_for_isolated_tests() -> None:
    key = Fernet.generate_key().decode()

    assert isinstance(get_fernet(key), Fernet)
