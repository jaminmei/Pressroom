from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.execution import NodeOutput
from app.services import adaptor_workbench as service


@pytest.mark.asyncio
async def test_workbench_executes_ephemerally_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        close=AsyncMock(),
        process=AsyncMock(return_value=NodeOutput(text="ok")),
    )
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(adaptor_sandbox_broker_url="http://adaptor-sandbox-broker:8080"),
    )
    monkeypatch.setattr(service, "assert_adaptor_sandbox_ready", AsyncMock())

    output = await service.execute_adaptor_workbench(
        code="def main(inputs): return {}",
        inputs={"sample": NodeOutput(text="input")},
        sandbox_client_factory=lambda **_kwargs: client,
    )

    assert output.text == "ok"
    client.process.assert_awaited_once()
    assert client.process.await_args.kwargs["request_id"].startswith("workbench:")
    client.close.assert_awaited_once()
