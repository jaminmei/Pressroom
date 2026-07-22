"""app/providers/auth_registry.py
--------------------------------
Extensible registry for auth type resolution strategies.

Built-in types (``none``, ``api_key``) are registered at import time.
Additional types can register themselves by calling
:func:`register_strategy` during application startup.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.providers.models import ModelProviderRow

from app.providers.auth import AuthResult, ResolverContext

logger = logging.getLogger(__name__)

AuthStrategyFn = Callable[..., Awaitable[AuthResult]]


class AuthStrategyRegistry:
    """Dictionary-based registry that maps auth type identifiers to resolver callables.

    Usage::

        from app.providers.auth_registry import registry

        # Register a custom auth strategy
        registry.register("custom_auth", my_custom_resolver)

        # Resolve credentials
        result = await registry.resolve("custom_auth", provider, ctx=ctx)
    """

    def __init__(self) -> None:
        self._strategies: dict[str, AuthStrategyFn] = {}

    def register(self, auth_type: str, resolver: AuthStrategyFn) -> None:
        """Register a resolver callable for *auth_type*.

        Args:
            auth_type: Auth type identifier string (e.g. ``"custom_auth"``).
            resolver: Async callable ``(provider, **kwargs) -> AuthResult``.

        Raises:
            ValueError: If *auth_type* is already registered.
        """
        if auth_type in self._strategies:
            raise ValueError(
                f"Auth type {auth_type!r} is already registered. "
                "Use a different identifier or unregister first."
            )
        self._strategies[auth_type] = resolver
        logger.debug("Registered auth strategy: %s", auth_type)

    def unregister(self, auth_type: str) -> None:
        """Remove a previously registered auth type.

        Args:
            auth_type: The identifier to remove.

        Raises:
            KeyError: If *auth_type* is not registered.
        """
        del self._strategies[auth_type]
        logger.debug("Unregistered auth strategy: %s", auth_type)

    async def resolve(
        self, auth_type: str, provider: ModelProviderRow, *, ctx: ResolverContext
    ) -> AuthResult:
        """Resolve authentication credentials for *auth_type*.

        Args:
            auth_type: The auth type identifier string.
            provider: The provider row to resolve credentials for.
            **kwargs: Additional keyword arguments forwarded to the resolver.

        Returns:
            An :class:`AuthResult` from the registered resolver.

        Raises:
            ValueError: If *auth_type* is not registered.
        """
        resolver = self._strategies.get(auth_type)
        if resolver is None:
            raise ValueError(
                f"Unsupported auth type: {auth_type!r}. "
                f"Registered types: {list(self._strategies.keys())}"
            )
        return await resolver(provider, ctx=ctx)

    def has(self, auth_type: str) -> bool:
        """Check whether *auth_type* is registered."""
        return auth_type in self._strategies

    def registered_types(self) -> list[str]:
        """Return a sorted list of all registered auth type identifiers."""
        return sorted(self._strategies.keys())

    def is_empty(self) -> bool:
        """Return ``True`` if no strategies are registered."""
        return len(self._strategies) == 0


registry = AuthStrategyRegistry()


def register_builtin_strategies() -> None:
    """Register the built-in ``none`` and ``api_key`` auth strategies.

    Called once during application startup. Safe to call multiple times
    (subsequent calls are no-ops because ``register()`` raises on duplicates).
    """
    from app.providers.auth import _resolve_api_key, _resolve_none

    if not registry.has("none"):
        registry.register("none", _resolve_none)
    if not registry.has("api_key"):
        registry.register("api_key", _resolve_api_key)
