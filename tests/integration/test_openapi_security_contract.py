from __future__ import annotations

from collections.abc import Mapping
from typing import Final, cast

from app.main import app

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


def _openapi_paths() -> Mapping[str, Mapping[str, Mapping[str, object]]]:
    return cast(Mapping[str, Mapping[str, Mapping[str, object]]], app.openapi()["paths"])


def _response_schema(operation: Mapping[str, object]) -> Mapping[str, object] | None:
    responses = cast(Mapping[str, Mapping[str, object]], operation["responses"])
    success = next(
        (
            response
            for status, response in responses.items()
            if status.startswith("2") and "content" in response
        ),
        None,
    )
    if success is None:
        return None
    content = cast(Mapping[str, Mapping[str, object]], success["content"])
    media = content.get("application/json")
    if media is None:
        return None
    return cast(Mapping[str, object] | None, media.get("schema"))


def test_protected_routes_advertise_their_auth_scheme() -> None:
    # Given: the generated OpenAPI contract
    paths = _openapi_paths()

    # When/Then: every protected operation advertises exactly its actual auth family.
    for path, methods in paths.items():
        for method, operation in methods.items():
            key = (method.upper(), path)
            if key in PUBLIC_ROUTES:
                assert operation.get("security") in (None, [])
                continue

            security = operation.get("security")
            assert security not in (None, []), key
            assert isinstance(security, list), key
            scheme_names = {name for entry in security for name in entry}
            if path.startswith("/api/v1/"):
                assert scheme_names == {"HTTPBearer"}, key
            else:
                assert scheme_names == {"SessionCookie"}, key


def test_application_error_responses_use_canonical_schema_refs() -> None:
    # Given: the generated OpenAPI contract
    paths = _openapi_paths()

    # When/Then: protected internal APIs document the canonical error statuses.
    for path, methods in paths.items():
        if path.startswith("/api/v1/"):
            continue
        for method, operation in methods.items():
            key = (method.upper(), path)
            if key in PUBLIC_ROUTES:
                continue
            responses = cast(Mapping[str, Mapping[str, object]], operation["responses"])
            for status in ("401", "403", "404", "409", "422"):
                schema = cast(
                    Mapping[str, object],
                    cast(
                        Mapping[str, Mapping[str, object]],
                        responses[status]["content"],
                    )["application/json"]["schema"],
                )
                assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (key, status)


def test_success_responses_use_concrete_schemas() -> None:
    # Given: the generated OpenAPI contract
    paths = _openapi_paths()
    route_prefixes = ("/api/files/", "/api/engines", "/api/workspaces", "/api/providers")

    # When/Then: JSON success responses are typed, not anonymous empty objects.
    for path, methods in paths.items():
        if not path.startswith(route_prefixes):
            continue
        for method, operation in methods.items():
            schema = _response_schema(operation)
            if schema is None:
                continue
            assert schema not in ({}, {"type": "object"}), (method.upper(), path)
