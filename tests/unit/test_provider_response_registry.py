from app.api.provider_response_registry import ProviderResponseEnricherRegistry


def test_registry_dispatches_without_auth_type_specific_core_logic() -> None:
    registry = ProviderResponseEnricherRegistry()
    registry.register("custom-auth", lambda: {"tenant_hint": "example"})

    assert registry.enrich("custom-auth") == {"tenant_hint": "example"}
    assert registry.enrich("none") is None
