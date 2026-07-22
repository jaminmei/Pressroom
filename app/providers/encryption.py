"""Fernet symmetric encryption utilities for protecting API keys at rest.

This module encrypts provider secrets with a stable Fernet key supplied by the
runtime. Public deployments fail closed when the key is absent.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


def get_fernet(key: str | None = None) -> Fernet:
    """Return a :class:`~cryptography.fernet.Fernet` instance.

    Resolution order for the encryption key:

    1. The ``key`` argument (if provided and not ``None``).
    2. The ``PROVIDER_ENCRYPTION_KEY`` environment variable.
    Args:
        key: Optional Fernet key as a URL-safe base64-encoded string.

    Returns:
        A configured :class:`~cryptography.fernet.Fernet` instance.

    Raises:
        EncryptionError: If *key* is provided but is not a valid Fernet key.
    """
    resolved_key: str

    if key is not None:
        resolved_key = key
    else:
        env_key = os.environ.get("PROVIDER_ENCRYPTION_KEY")
        if env_key:
            resolved_key = env_key
        else:
            raise EncryptionError("PROVIDER_ENCRYPTION_KEY is required")

    try:
        return Fernet(resolved_key.encode())
    except (ValueError, Exception) as e:
        raise EncryptionError(f"Invalid encryption key: {e}") from e


def encrypt(plaintext: str, fernet: Fernet) -> str:
    """Encrypt *plaintext* and return the Fernet token as a string.

    Args:
        plaintext: The sensitive string to encrypt (e.g. an API key).
        fernet: A :class:`~cryptography.fernet.Fernet` instance obtained from
            :func:`get_fernet`.

    Returns:
        The encrypted token as a URL-safe base64-encoded string.
    """
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, fernet: Fernet) -> str:
    """Decrypt a Fernet token and return the original plaintext.

    Args:
        ciphertext: A Fernet token string previously produced by
            :func:`encrypt`.
        fernet: A :class:`~cryptography.fernet.Fernet` instance that holds the
            same key used during encryption.

    Returns:
        The decrypted plaintext string.

    Raises:
        EncryptionError: If the token is invalid or was encrypted with a
            different key.
    """
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise EncryptionError("Decryption failed: invalid token or wrong key") from e
