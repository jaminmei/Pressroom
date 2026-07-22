"""app.providers package."""

from app.providers.auth import AuthResolver, AuthResult, CredentialKind, ResolverContext
from app.providers.auth_registry import register_builtin_strategies, registry

__all__ = [
    "AuthResult",
    "AuthResolver",
    "CredentialKind",
    "ResolverContext",
    "registry",
    "register_builtin_strategies",
]
