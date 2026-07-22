"""app/providers/auth.py
-----------------------
Auth resolution for model providers.

Supports two built-in auth strategies:
- ``none``     — no credentials required
- ``api_key``  — Fernet-encrypted API key stored in ModelProviderRow

Additional strategies can be registered via :mod:`app.providers.auth_registry`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet

from app.providers.encryption import decrypt

if TYPE_CHECKING:
    from app.providers.models import ModelProviderRow


class CredentialKind(str, Enum):
    """How a resolved credential must be presented to an upstream adapter."""

    none = "none"
    api_key = "api_key"
    bearer = "bearer"


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Resolved authentication credentials for a provider call."""

    kind: CredentialKind = CredentialKind.none
    credential: str | None = None

    def __post_init__(self) -> None:
        credential = self.credential.strip() if isinstance(self.credential, str) else None
        if self.kind == CredentialKind.none:
            if credential is not None:
                raise ValueError("none credentials cannot carry a secret")
            return
        if not credential:
            raise ValueError(f"{self.kind.value} credentials require a non-empty secret")
        object.__setattr__(self, "credential", credential)


@dataclass
class ResolverContext:
    """Context passed to every auth strategy resolver."""

    fernet: Fernet


async def _resolve_none(provider: ModelProviderRow, *, ctx: ResolverContext) -> AuthResult:
    return AuthResult()


async def _resolve_api_key(provider: ModelProviderRow, *, ctx: ResolverContext) -> AuthResult:
    if provider.api_key is None:
        raise ValueError(f"Missing API key for provider {provider.id!r}")
    decrypted = decrypt(provider.api_key, ctx.fernet)
    return AuthResult(kind=CredentialKind.api_key, credential=decrypted)


class AuthResolver:
    """Resolve authentication credentials for a :class:`ModelProviderRow`.

    Delegates to :data:`app.providers.auth_registry.registry` for actual
    resolution. Built-in ``none`` and ``api_key`` strategies are registered
    during application startup.

    Args:
        fernet: A :class:`~cryptography.fernet.Fernet` instance used to
            decrypt stored secrets.
    """

    def __init__(self, *, fernet: Fernet) -> None:
        self._ctx = ResolverContext(fernet=fernet)

    async def resolve(self, provider: ModelProviderRow) -> AuthResult:
        """Return an :class:`AuthResult` for *provider*.

        Args:
            provider: The provider row whose auth_type drives resolution.

        Returns:
            An :class:`AuthResult` populated with the appropriate credential.

        Raises:
            ValueError: If ``provider.auth_type`` is not a recognised value.
        """
        from app.providers.auth_registry import registry

        auth_type = str(provider.auth_type)
        return await registry.resolve(auth_type, provider, ctx=self._ctx)
