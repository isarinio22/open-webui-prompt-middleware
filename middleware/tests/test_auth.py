import httpx
import pytest
import respx

from tests.conftest import CHAT_BODY, COMPLETION

pytestmark = pytest.mark.parametrize(
    "settings_overrides", [{"middleware_api_key": "client-secret"}]
)


async def test_wrong_key_is_rejected_in_openai_error_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "message": "Invalid or missing API key.",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }


async def test_missing_key_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")

    assert response.status_code == 401


async def test_correct_key_is_accepted(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models", headers={"Authorization": "Bearer client-secret"})

    assert response.status_code == 200


async def test_chat_route_requires_key(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 401
    assert not route.called


async def test_health_endpoints_need_no_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
