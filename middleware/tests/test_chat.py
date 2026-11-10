import json
from typing import Any

import httpx
import pytest
import respx

from tests import recorded
from tests.conftest import CHAT_BODY, COMPLETION, TEST_PROMPT, UPSTREAM_API_KEY


def forwarded_body(route: respx.Route) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


async def test_forwards_prompt_first_and_preserves_other_fields(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)
    body = {**CHAT_BODY, "temperature": 0.2, "max_tokens": 50, "user": "u-1"}

    await client.post("/v1/chat/completions", json=body)

    assert forwarded_body(route) == {
        **body,
        "messages": [{"role": "system", "content": TEST_PROMPT}, *body["messages"]],
    }


async def test_returns_upstream_response_unchanged(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.post("/chat/completions").respond(200, json=COMPLETION)

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 200
    assert response.json() == COMPLETION


async def test_sends_our_openai_key_not_the_clients(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post(
        "/v1/chat/completions", json=CHAT_BODY, headers={"Authorization": "Bearer from-open-webui"}
    )

    assert route.calls.last.request.headers["authorization"] == f"Bearer {UPSTREAM_API_KEY}"


async def test_title_call_is_forwarded_unchanged(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post("/v1/chat/completions", json=recorded.TITLE_CALL)

    assert forwarded_body(route) == recorded.TITLE_CALL


@pytest.mark.parametrize("settings_overrides", [{"inject_on_internal_tasks": True}])
async def test_internal_task_gets_prompt_when_enabled(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post("/v1/chat/completions", json=recorded.TITLE_CALL)

    assert forwarded_body(route)["messages"][0] == {"role": "system", "content": TEST_PROMPT}


async def test_user_system_prompt_stays_after_ours(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post("/v1/chat/completions", json=recorded.WITH_USER_SYSTEM_PROMPT)

    assert forwarded_body(route)["messages"] == [
        {"role": "system", "content": TEST_PROMPT},
        *recorded.WITH_USER_SYSTEM_PROMPT["messages"],
    ]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"not json", id="invalid_json"),
        pytest.param(b'{"model": "gpt-4o-mini"}', id="missing_messages"),
        pytest.param(b"[]", id="not_an_object"),
    ],
)
async def test_rejects_malformed_body(client: httpx.AsyncClient, content: bytes) -> None:
    response = await client.post(
        "/v1/chat/completions", content=content, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_body"


async def test_rejects_a_model_that_is_not_allowed(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(200, json=COMPLETION)

    response = await client.post("/v1/chat/completions", json={**CHAT_BODY, "model": "o1-pro"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"
    assert not route.called


async def test_rejects_stream_given_as_a_string(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/chat/completions", json={**CHAT_BODY, "stream": "false"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_body"


async def test_accepts_stream_null_as_not_streamed(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.post("/chat/completions").respond(200, json=COMPLETION)

    response = await client.post("/v1/chat/completions", json={**CHAT_BODY, "stream": None})

    assert response.status_code == 200
    assert response.json() == COMPLETION
