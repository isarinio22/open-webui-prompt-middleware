from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import respx

from tests.conftest import CHAT_BODY, COMPLETION

LogLines = Callable[[], list[dict[str, object]]]


async def test_retries_after_503_and_logs_each_attempt(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    route = upstream.post("/chat/completions")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=COMPLETION)]

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 200
    assert response.json() == COMPLETION
    attempts = [line["attempt"] for line in log_lines() if line["event"] == "upstream.request"]
    assert attempts == [1, 2]


async def test_retries_connection_errors(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions")
    route.side_effect = [httpx.ConnectError("refused"), httpx.Response(200, json=COMPLETION)]

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 200
    assert route.call_count == 2


async def test_gives_up_after_max_retries_with_exponential_backoff(
    client: httpx.AsyncClient, upstream: respx.MockRouter, backoff_waits: list[float]
) -> None:
    route = upstream.post("/chat/completions").respond(503)

    response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 502
    assert route.call_count == 3
    assert backoff_waits == [0.5, 1.0]


@pytest.mark.parametrize("status", [400, 429])
async def test_does_not_retry_client_errors(
    client: httpx.AsyncClient, upstream: respx.MockRouter, status: int
) -> None:
    route = upstream.post("/chat/completions").respond(status, json={"error": {"message": "x"}})

    await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert route.call_count == 1


@pytest.mark.parametrize("settings_overrides", [{"upstream_max_retries": 0}])
async def test_zero_retries_means_one_attempt(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").respond(503)

    await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert route.call_count == 1


async def test_streaming_request_retries_before_first_byte(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    async def one_chunk() -> AsyncIterator[bytes]:
        yield b"data: [DONE]\n\n"

    route = upstream.post("/chat/completions")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, content=one_chunk(), headers={"Content-Type": "text/event-stream"}),
    ]

    response = await client.post("/v1/chat/completions", json={**CHAT_BODY, "stream": True})

    assert response.status_code == 200
    assert response.content == b"data: [DONE]\n\n"
    assert route.call_count == 2
