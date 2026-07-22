"""Generic registration-module loader for optional Provider integrations."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable
from threading import RLock
from types import ModuleType

PROVIDER_PLUGIN_MODULES_ENV = "PROVIDER_PLUGIN_MODULES"
_registration_lock = RLock()
_loaded_plugin_modules: set[str] = set()


class ProviderPluginError(RuntimeError):
    """Raised when an explicitly configured Provider plugin cannot register."""


def _configured_modules(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))


def _register_module(module: ModuleType, module_name: str) -> None:
    register = getattr(module, "register", None)
    if not callable(register):
        raise ProviderPluginError(
            f"Provider plugin module {module_name!r} must expose a callable register()"
        )
    register()


def load_provider_plugins(module_names: Iterable[str] | None = None) -> tuple[str, ...]:
    """Import and register explicitly configured optional integration modules.

    Public builds configure no modules. Downstream distributions can provide
    their own modules without adding feature names or imports to the core.
    """

    names = (
        tuple(dict.fromkeys(name.strip() for name in module_names if name.strip()))
        if module_names is not None
        else _configured_modules(os.getenv(PROVIDER_PLUGIN_MODULES_ENV, ""))
    )
    with _registration_lock:
        for module_name in names:
            if module_name in _loaded_plugin_modules:
                continue
            try:
                module = importlib.import_module(module_name)
                _register_module(module, module_name)
            except ProviderPluginError:
                raise
            except Exception as exc:
                raise ProviderPluginError(
                    f"Provider plugin module {module_name!r} failed to register"
                ) from exc
            _loaded_plugin_modules.add(module_name)
    return names


def bootstrap_provider_registry(module_names: Iterable[str] | None = None) -> tuple[str, ...]:
    """Register built-in and configured Provider auth strategies once per process.

    Both API and worker processes call this entry point. Repeated worker signals,
    task entry checks, and prefork inheritance are safe because plugin modules are
    registered at most once in each process.
    """

    from app.providers.auth_registry import register_builtin_strategies

    with _registration_lock:
        register_builtin_strategies()
        return load_provider_plugins(module_names)


__all__ = [
    "PROVIDER_PLUGIN_MODULES_ENV",
    "ProviderPluginError",
    "bootstrap_provider_registry",
    "load_provider_plugins",
]
