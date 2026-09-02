from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.config import get_settings
from app.models.execution import NodeOutput
from app.services.adaptor_executor import (
    assert_adaptor_sandbox_ready,
    validate_adaptor_sandbox_broker_url,
)
from app.services.sandbox_client import SandboxClient


async def execute_adaptor_workbench(
    *,
    code: str,
    inputs: dict[str, NodeOutput],
    sandbox_client_factory: Callable[..., SandboxClient] = SandboxClient,
) -> NodeOutput:
    """Run one non-persistent Adaptor test through the production sandbox path."""
    broker_url = validate_adaptor_sandbox_broker_url(get_settings().adaptor_sandbox_broker_url)
    client = sandbox_client_factory(base_url=broker_url)
    try:
        await assert_adaptor_sandbox_ready(client)
        return await client.process(
            request_id=f"workbench:{uuid4().hex}",
            code=code,
            inputs=inputs,
        )
    finally:
        await client.close()
