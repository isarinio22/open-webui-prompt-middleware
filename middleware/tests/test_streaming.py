import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import respx

from tests.conftest import CHAT_BODY, TEST_PROMPT

STREAM_BODY: dict[str, Any] = {**CHAT_BODY, "stream": True}
SSE_CHUNKS = [
    b'data: {"choices":[{"delta":{"content":"Inv"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"oice"}}]}\n\n',
    b"data: [DONE]\n\n",
]


async def sse_stream() -> AsyncIterator[bytes]:
    for chunk in SSE_CHUNKS:
        yield chunk


async def sse_stream_that_breaks() -> AsyncIterator[bytes]:
    yield SSE_CHUNKS[0]
    raise httpx.ReadError("connection reset")


def streaming_response(content: AsyncIterator[bytes]) -> httpx.Response:
    return httpx.Response(200, content=content, headers={"Content-Type": "text/event-stream"})


async def test_relays_sse_chunks_in_order(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.post("/chat/completions").mock(return_value=streaming_response(sse_stream()))

    response = await client.post("/v1/chat/completions", json=STREAM_BODY)

    assert response.status_code == 200
    assert response.content == b"".join(SSE_CHUNKS)


async def test_sets_streaming_headers(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.post("/chat/completions").mock(return_value=streaming_response(sse_stream()))

    response = await client.post("/v1/chat/completions", json=STREAM_BODY)

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


async def test_streamed_request_gets_prompt_and_keeps_stream_flag(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").mock(return_value=streaming_response(sse_stream()))

    await client.post("/v1/chat/completions", json=STREAM_BODY)

    forwarded = json.loads(route.calls.last.request.content)
    assert forwarded["stream"] is True
    assert forwarded["messages"][0] == {"role": "system", "content": TEST_PROMPT}


async def test_mid_stream_failure_ends_with_error_event_and_done(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    route = upstream.post("/chat/completions").mock(
        return_value=streaming_response(sse_stream_that_breaks())
    )

    response = await client.post("/v1/chat/completions", json=STREAM_BODY)

    data_lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    assert response.status_code == 200
    assert data_lines[0] == SSE_CHUNKS[0].decode().strip()
    error = json.loads(data_lines[1].removeprefix("data: "))
    assert error["error"]["code"] == "upstream_stream_interrupted"
    assert data_lines[2] == "data: [DONE]"
    assert route.call_count == 1


async def test_streamed_client_error_passes_through_as_json(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    openai_error = {
        "error": {"message": "Bad model", "type": "invalid_request_error", "code": None}
    }
    upstream.post("/chat/completions").respond(400, json=openai_error)

    response = await client.post("/v1/chat/completions", json=STREAM_BODY)

    assert response.status_code == 400
    assert response.json() == openai_error


async def test_streamed_auth_error_maps_to_502(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.post("/chat/completions").respond(401, json={"error": {"message": "bad key"}})

    response = await client.post("/v1/chat/completions", json=STREAM_BODY)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_auth_misconfigured"
