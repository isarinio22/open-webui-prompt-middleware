import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import respx

from tests.conftest import CHAT_BODY, COMPLETION, UPSTREAM_API_KEY

LogLines = Callable[[], list[dict[str, object]]]


async def test_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models", headers={"X-Request-ID": "abc-123"})

    assert response.headers["x-request-id"] == "abc-123"


async def test_request_id_is_generated_when_absent(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")

    uuid.UUID(response.headers["x-request-id"])


async def test_lifecycle_events_carry_request_id(
    client: httpx.AsyncClient, log_lines: LogLines
) -> None:
    await client.get("/v1/models", headers={"X-Request-ID": "abc-123"})

    events = {line["event"]: line for line in log_lines()}
    assert events["request.received"]["request_id"] == "abc-123"
    assert events["request.received"]["path"] == "/v1/models"
    assert events["request.completed"]["request_id"] == "abc-123"
    assert events["request.completed"]["status"] == 200
    assert isinstance(events["request.completed"]["duration_ms"], int)


async def test_api_key_never_appears_in_logs(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    upstream.get("/models").mock(side_effect=httpx.ConnectError("refused"))
    # OpenAI's real 401 body quotes part of the key; make ours quote all of it.
    upstream.post("/chat/completions").respond(401, json={"error": {"message": UPSTREAM_API_KEY}})

    await client.get("/ready")
    await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert log_lines()
    for line in log_lines():
        assert UPSTREAM_API_KEY not in str(line)


async def test_chat_lifecycle_events_are_logged_in_order(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post("/v1/chat/completions", json=CHAT_BODY, headers={"X-Request-ID": "chat-1"})

    events = [line["event"] for line in log_lines() if line["request_id"] == "chat-1"]
    assert events == [
        "request.received",
        "chat.request",
        "injection.applied",
        "upstream.request",
        "upstream.completed",
        "request.completed",
    ]


async def test_chat_request_event_describes_the_body(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    upstream.post("/chat/completions").respond(200, json=COMPLETION)
    body = {**CHAT_BODY, "messages": [{"role": "system", "content": "x"}, *CHAT_BODY["messages"]]}

    await client.post("/v1/chat/completions", json=body)

    chat = next(line for line in log_lines() if line["event"] == "chat.request")
    assert chat["model"] == "gpt-4o-mini"
    assert chat["stream"] is False
    assert chat["message_count"] == 2
    assert chat["has_client_system_message"] is True


async def test_upstream_failure_logs_error_type_and_mapped_status(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    upstream.post("/chat/completions").mock(side_effect=httpx.ConnectError("refused"))

    await client.post("/v1/chat/completions", json=CHAT_BODY)

    failed = next(line for line in log_lines() if line["event"] == "request.failed")
    assert failed["level"] == "ERROR"
    assert failed["error_type"] == "upstream_unreachable"
    assert failed["mapped_status"] == 502


async def test_message_content_is_not_logged_by_default(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert "Invoice #42" not in str(log_lines())


@pytest.mark.parametrize("settings_overrides", [{"log_message_content": True}])
async def test_message_content_is_logged_when_enabled(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    upstream.post("/chat/completions").respond(200, json=COMPLETION)

    await client.post("/v1/chat/completions", json=CHAT_BODY)

    chat = next(line for line in log_lines() if line["event"] == "chat.request")
    assert chat["messages"] == CHAT_BODY["messages"]


async def test_stream_lifecycle_ends_after_the_last_chunk(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    async def two_chunks() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[]}\n\n'
        yield b"data: [DONE]\n\n"

    upstream.post("/chat/completions").respond(
        200, content=two_chunks(), headers={"Content-Type": "text/event-stream"}
    )

    await client.post(
        "/v1/chat/completions",
        json={**CHAT_BODY, "stream": True},
        headers={"X-Request-ID": "stream-1"},
    )

    lines = [line for line in log_lines() if line["request_id"] == "stream-1"]
    assert [line["event"] for line in lines] == [
        "request.received",
        "chat.request",
        "injection.applied",
        "upstream.request",
        "upstream.first_byte",
        "upstream.completed",
        "request.completed",
    ]
    completed = next(line for line in lines if line["event"] == "upstream.completed")
    assert completed["chunks"] == 2


async def test_mid_stream_failure_is_logged_at_error(
    client: httpx.AsyncClient, upstream: respx.MockRouter, log_lines: LogLines
) -> None:
    async def breaks() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[]}\n\n'
        raise httpx.ReadError("connection reset")

    upstream.post("/chat/completions").respond(
        200, content=breaks(), headers={"Content-Type": "text/event-stream"}
    )

    await client.post("/v1/chat/completions", json={**CHAT_BODY, "stream": True})

    event = next(line for line in log_lines() if line["event"] == "upstream.stream_interrupted")
    assert event["level"] == "ERROR"
    assert event["error"] == "ReadError"
    assert event["chunks"] == 1
