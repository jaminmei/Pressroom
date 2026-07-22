from app.core.feature_flags import FeatureFlags, OrchestratorMode


def test_smoke_feature_flags_enum_is_available(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.delenv("ENABLE_QUEUE_MODE", raising=False)
    mode = FeatureFlags.get_orchestrator_mode()
    assert mode in {OrchestratorMode.SERIAL, OrchestratorMode.QUEUE}


def test_orchestrator_mode_takes_precedence_over_enable_queue_mode(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", "serial")
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "true")

    assert FeatureFlags.get_orchestrator_mode() == OrchestratorMode.SERIAL


def test_enable_queue_mode_true_maps_to_queue(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "true")

    assert FeatureFlags.get_orchestrator_mode() == OrchestratorMode.QUEUE


def test_enable_queue_mode_false_maps_to_serial(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "false")

    assert FeatureFlags.get_orchestrator_mode() == OrchestratorMode.SERIAL


def test_empty_orchestrator_mode_allows_enable_queue_mode_compat(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_MODE", " ")
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "true")

    assert FeatureFlags.get_orchestrator_mode() == OrchestratorMode.QUEUE


def test_enable_queue_mode_invalid_value_raises(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_MODE", raising=False)
    monkeypatch.setenv("ENABLE_QUEUE_MODE", "invalid")

    try:
        FeatureFlags.get_orchestrator_mode()
    except ValueError as exc:
        assert "Invalid ENABLE_QUEUE_MODE value" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid ENABLE_QUEUE_MODE")
