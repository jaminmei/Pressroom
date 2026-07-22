from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

from fastapi.dependencies.models import Dependant
from starlette.routing import BaseRoute

from app.main import app

PolicyKind = Literal[
    "public",
    "authenticated_global",
    "workspace",
    "explicit_workspace",
    "public_api_key",
    "internal_attestation",
]


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    kind: PolicyKind
    capability: str | None = None


RouteKey = tuple[str, str]
PUBLIC: Final = RoutePolicy("public")
AUTHENTICATED_GLOBAL: Final = RoutePolicy("authenticated_global")
PUBLIC_API_KEY: Final = RoutePolicy("public_api_key")
INTERNAL_ATTESTATION: Final = RoutePolicy("internal_attestation")

PUBLIC_ROUTES: Final = {
    ("GET", "/api/health"),
    ("GET", "/api/health/detailed"),
    ("GET", "/api/health/worker"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/nodes/registry"),
    ("GET", "/api/v1/health"),
}

AUTHENTICATED_GLOBAL_ROUTES: Final = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/workspaces"),
    ("GET", "/api/workspaces"),
    ("GET", "/api/workspaces/session"),
}

INTERNAL_ATTESTATION_ROUTES: Final = {
    ("POST", "/api/internal/runtime-attestation"),
}

EXPLICIT_WORKSPACE_ROUTES: Final[dict[RouteKey, str]] = {
    ("POST", "/api/workspaces/{workspace_id}/switch"): "workspace.view",
    ("PATCH", "/api/workspaces/{workspace_id}"): "workspace.update_settings",
    ("GET", "/api/workspaces/{workspace_id}/members"): "workspace.view",
    ("POST", "/api/workspaces/{workspace_id}/members"): "workspace.manage_members",
    ("PATCH", "/api/workspaces/{workspace_id}/members/{user_id}"): "workspace.manage_members",
    ("DELETE", "/api/workspaces/{workspace_id}/members/{user_id}"): "workspace.manage_members",
    ("POST", "/api/workspaces/{workspace_id}/transfer-owner"): "workspace.transfer_owner",
    ("DELETE", "/api/workspaces/{workspace_id}"): "workspace.delete",
    ("GET", "/api/workspaces/{workspace_id}/deletion-impact"): "workspace.delete",
    ("GET", "/api/workspaces/{workspace_id}/audit-events"): "workspace.update_settings",
    ("POST", "/api/test-sets/{test_set_id}/documents/upload"): "document.upload",
    ("GET", "/api/test-sets/{test_set_id}/documents"): "dataset.view",
    ("GET", "/api/test-sets/{test_set_id}/documents/{document_id}"): "dataset.view",
    ("GET", "/api/test-sets/{test_set_id}/documents/{document_id}/file"): "dataset.view",
    ("GET", "/api/test-sets/{test_set_id}/documents/{document_id}/thumbnail"): "dataset.view",
    ("DELETE", "/api/test-sets/{test_set_id}/documents/{document_id}"): "document.upload",
    (
        "POST",
        "/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth",
    ): "ground_truth.manage",
    ("GET", "/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth"): "dataset.view",
    (
        "GET",
        "/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/versions",
    ): "dataset.view",
    (
        "POST",
        "/api/test-sets/{test_set_id}/documents/{document_id}/ground-truth/apply",
    ): "ground_truth.manage",
    ("POST", "/api/admin/api-keys"): "api_key.manage",
    ("GET", "/api/admin/api-keys"): "api_key.manage",
    ("POST", "/api/admin/api-keys/{key_id}/revoke"): "api_key.manage",
    ("GET", "/api/admin/workflows/{workflow_id}/api-usage/summary"): "api_usage.view",
    ("GET", "/api/admin/workflows/{workflow_id}/api-usage/runs"): "api_usage.view",
    (
        "GET",
        "/api/admin/workflows/{workflow_id}/api-usage/runs/{workflow_run_id}/trace",
    ): "api_usage.view",
}


@runtime_checkable
class IncludedRoute(Protocol):
    def effective_candidates(self) -> list[BaseRoute]: ...


@runtime_checkable
class EffectiveRoute(Protocol):
    path: str
    methods: set[str]
    dependant: Dependant


def _routes(routes: Iterable[BaseRoute]) -> Iterator[EffectiveRoute]:
    for route in routes:
        match route:  # FastAPI route types are an open hierarchy.
            case IncludedRoute():
                yield from _routes(route.effective_candidates())
            case EffectiveRoute():
                yield route
            case _:
                continue


def _policy(route: EffectiveRoute) -> RoutePolicy | None:
    key = (next(iter(route.methods)), route.path)
    if key in PUBLIC_ROUTES:
        return PUBLIC
    if key in AUTHENTICATED_GLOBAL_ROUTES:
        return AUTHENTICATED_GLOBAL
    if key in INTERNAL_ATTESTATION_ROUTES:
        return INTERNAL_ATTESTATION
    if capability := EXPLICIT_WORKSPACE_ROUTES.get(key):
        return RoutePolicy("explicit_workspace", capability)

    for dependency in route.dependant.dependencies:
        dependency_call = dependency.call
        assert dependency_call is not None
        policy_kind = getattr(dependency_call, "policy_kind", None)
        if policy_kind == "public_api_key":
            return PUBLIC_API_KEY
        if policy_kind == "workspace":
            capability = getattr(dependency_call, "capability", None)
            assert isinstance(capability, str)
            return RoutePolicy("workspace", capability)
    return None


def test_every_application_endpoint_has_an_access_policy() -> None:
    routes = list(_routes(app.routes))
    inventory = {
        (method, route.path): _policy(route) for route in routes for method in route.methods
    }

    assert inventory
    assert {key: policy for key, policy in inventory.items() if policy is None} == {}
    assert {policy.kind for policy in inventory.values() if policy is not None} == {
        "public",
        "authenticated_global",
        "workspace",
        "explicit_workspace",
        "public_api_key",
        "internal_attestation",
    }
    assert inventory[("GET", "/api/workspaces/{workspace_id}/audit-events")] == RoutePolicy(
        "explicit_workspace", "workspace.update_settings"
    )
    assert inventory[("GET", "/api/workspaces/{workspace_id}/deletion-impact")] == RoutePolicy(
        "explicit_workspace", "workspace.delete"
    )
    assert inventory[("GET", "/api/test-sets")] == RoutePolicy("workspace", "dataset.view")
    assert inventory[("POST", "/api/internal/runtime-attestation")] == INTERNAL_ATTESTATION
