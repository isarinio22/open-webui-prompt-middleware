from typing import Any

import httpx
import pytest
import respx

from tests.conftest import CHAT_BODY


@pytest.mark.parametrize(
    ("mock", "expected_status", "expected_code"),
    [
        pytest.param(
            {"side_effect": httpx.ConnectError("refused")},
            502,
            "upstream_unreachable",
            id="connect",
        ),
        pytest.param(
            {"side_effect": httpx.ReadTimeout("slow")}, 504, "upstream_timeout", id="timeout"
        ),
        pytest.param(
            {"return_value": httpx.Response(401)}, 502, "upstream_auth_misconfigured", id="401"
        ),
        pytest.param(
            {"return_value": httpx.Response(403)}, 502, "upstream_auth_misconfigured", id="403"
        ),
        pytest.param({"return_value": httpx.Response(500)}, 502, "upstream_server_error", id="500"),
        pytest.param({"return_value": httpx.Response(503)}, 502, "upstream_server_error", id="503"),
    ],
)
async def test_maps_upstream_failure_to_openai_error(
    client: httpx.AsyncClient,
    upstream: respx.MockRouter,
    mock: dict[str, Any],
    expected_status: int,
    expected_code: str,
) -> None:
    upstream.post("/chat/completions").mock(**mock)

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == expected_status
    assert response.json()["error"]["type"] == "upstream_error"
    assert response.json()["error"]["code"] == expected_code


async def test_auth_failure_hides_openai_message(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    openai_error = {"error": {"message": "Incorrect API key provided: sk-tes***-log"}}
    upstream.post("/chat/completions").respond(401, json=openai_error)

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert "Incorrect API key" not in response.text
    assert "sk-" not in response.text


async def test_rate_limit_passes_status_body_and_retry_after(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    openai_error = {"error": {"message": "Rate limit reached", "type": "requests", "code": None}}
    upstream.post("/chat/completions").respond(
        429, json=openai_error, headers={"Retry-After": "20"}
    )

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "20"
    assert response.json() == openai_error


async def test_other_client_errors_pass_through(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    openai_error = {
        "error": {
            "message": "This model's maximum context length is 128000 tokens.",
            "type": "invalid_request_error",
            "code": "context_length_exceeded",
        }
    }
    upstream.post("/chat/completions").respond(400, json=openai_error)

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 400
    assert response.json() == openai_error
