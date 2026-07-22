from __future__ import annotations

import base64
import json
import logging

import httpx
import pytest
from openai import BadRequestError
from src.provider_transport import (
    ProviderAddressBlockedError,
    ProviderSafeTransport,
    is_allowed_provider_ip,
    provider_http_client,
)
from src.vlm_engine import CredentialKind, VLMEngine


def _completion(content: str = '{"result":"ok"}') -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "vision-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def _image() -> str:
    return base64.b64encode(b"fake-png").decode("ascii")


@pytest.mark.parametrize(
    ("kind", "credential", "expected_authorization"),
    [
        (CredentialKind.api_key, "sk-test", "Bearer sk-test"),
        (CredentialKind.bearer, "bearer-test", "Bearer bearer-test"),
        (CredentialKind.none, None, None),
    ],
)
def test_openai_adapter_sends_image_and_expected_auth(
    kind: CredentialKind,
    credential: str | None,
    expected_authorization: str | None,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion(), headers={"x-request-id": "req-openai"})

    result = VLMEngine().process_base64(
        _image(),
        {
            "provider_base_url": "https://provider.test/v1",
            "provider_api_style": "openai",
            "provider_ssl_verify": True,
            "model": "vision-model",
            "prompt": "extract the page",
        },
        credential_kind=kind,
        credential=credential,
        transport=httpx.MockTransport(handler),
    )

    assert result["result"] == "ok"
    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    if expected_authorization is None:
        assert "authorization" not in request.headers
    else:
        assert request.headers["authorization"] == expected_authorization
    payload = json.loads(request.content)
    image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    ("kind", "credential", "expected_header", "expected_value"),
    [
        (CredentialKind.api_key, "azure-key", "api-key", "azure-key"),
        (CredentialKind.bearer, "azure-token", "authorization", "Bearer azure-token"),
        (CredentialKind.none, None, None, None),
    ],
)
def test_azure_adapter_auth_and_version(
    kind: CredentialKind,
    credential: str | None,
    expected_header: str | None,
    expected_value: str | None,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion())

    result = VLMEngine().process_base64(
        _image(),
        {
            "provider_base_url": "https://resource.openai.azure.com",
            "provider_api_style": "azure_openai",
            "provider_api_version": "2025-04-01-preview",
            "model": "deployment-a",
        },
        credential_kind=kind,
        credential=credential,
        transport=httpx.MockTransport(handler),
    )

    assert result["result"] == "ok"
    request = requests[0]
    assert request.url.path == "/openai/deployments/deployment-a/chat/completions"
    assert request.url.params["api-version"] == "2025-04-01-preview"
    if expected_header is None:
        assert "api-key" not in request.headers
        assert "authorization" not in request.headers
    else:
        assert request.headers[expected_header] == expected_value


def test_provider_transport_pins_dns_and_preserves_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.provider_transport.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = ProviderSafeTransport(inner=httpx.MockTransport(handler), allow_private=False)
    with httpx.Client(transport=transport) as client:
        assert client.get("https://provider.example/models").status_code == 200

    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["host"] == "provider.example"
    assert seen[0].extensions["sni_hostname"] == b"provider.example"


def test_metadata_is_always_blocked_even_when_private_hosts_are_allowed() -> None:
    assert not is_allowed_provider_ip("169.254.169.254", allow_private=True)
    assert not is_allowed_provider_ip("fe80::1", allow_private=True)
    assert is_allowed_provider_ip("10.0.0.5", allow_private=True)
    assert not is_allowed_provider_ip("10.0.0.5", allow_private=False)


def test_transport_rejects_metadata_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.provider_transport.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("169.254.169.254", 80))],
    )
    transport = ProviderSafeTransport(inner=httpx.MockTransport(lambda _: httpx.Response(200)))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ProviderAddressBlockedError):
            client.get("http://169.254.169.254/latest/meta-data")


@pytest.mark.parametrize(
    ("addresses", "allow_private"),
    [
        (["8.8.8.8", "169.254.169.254"], True),
        (["8.8.8.8", "10.0.0.5"], False),
    ],
)
def test_transport_rejects_mixed_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
    addresses: list[str],
    allow_private: bool,
) -> None:
    monkeypatch.setattr(
        "src.provider_transport.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", (address, 443)) for address in addresses],
    )
    transport = ProviderSafeTransport(
        inner=httpx.MockTransport(lambda _: httpx.Response(200)),
        allow_private=allow_private,
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ProviderAddressBlockedError):
            client.get("https://provider.example/models")


def test_provider_client_does_not_follow_redirects_with_custom_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def resolve(_host: str, *_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(2, 1, 6, "", ("8.8.8.8", 80))]

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
            request=request,
        )

    monkeypatch.setattr("src.provider_transport.socket.getaddrinfo", resolve)
    with provider_http_client(
        verify=True,
        transport=ProviderSafeTransport(
            inner=httpx.MockTransport(redirect),
            allow_private=True,
        ),
    ) as client:
        response = client.get(
            "http://provider.example/start",
            headers={"api-key": "test-only-key"},
        )

    assert response.status_code == 302
    assert len(requests) == 1
    assert requests[0].headers["api-key"] == "test-only-key"


def test_logs_never_include_prompt_secret_or_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="src.vlm_engine")
    prompt = "PROMPT-SENTINEL"
    secret = "SECRET-SENTINEL"
    response_body = "RESPONSE-SENTINEL"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(f'{{"result":"{response_body}"}}'))

    VLMEngine().process_base64(
        _image(),
        {
            "provider_base_url": "https://provider.test/v1",
            "provider_api_style": "openai",
            "model": "vision-model",
            "prompt": prompt,
        },
        credential_kind=CredentialKind.api_key,
        credential=secret,
        transport=httpx.MockTransport(handler),
    )

    logs = caplog.text
    assert prompt not in logs
    assert secret not in logs
    assert response_body not in logs


def test_error_logs_do_not_include_upstream_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="src.vlm_engine")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="PRIVATE-UPSTREAM-BODY", request=request)

    with pytest.raises(BadRequestError):
        VLMEngine().process_base64(
            _image(),
            {
                "provider_base_url": "https://provider.test/v1",
                "provider_api_style": "openai",
                "model": "vision-model",
            },
            transport=httpx.MockTransport(handler),
        )

    assert "PRIVATE-UPSTREAM-BODY" not in caplog.text
