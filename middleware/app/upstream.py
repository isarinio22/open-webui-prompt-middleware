import logging
import time
from asyncio import CancelledError, sleep
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Response
from fastapi.responses import StreamingResponse

from app.config import Settings
from app.logging import elapsed_ms
from app.schemas import ApiError, ErrorDetail, ErrorResponse

log = logging.getLogger(__name__)

PROBE_CACHE_SECONDS = 30.0
# Shorter than Docker's 10-second healthcheck timeout, so a hanging OpenAI can't
# make probes pile up.
PROBE_TIMEOUT_SECONDS = 5.0
BACKOFF_BASE_SECONDS = 0.5

# no-cache stops caches from holding on to the stream. X-Accel-Buffering stops
# nginx-style proxies from buffering it, which would deliver the answer all at once.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def build_client(settings: Settings) -> httpx.AsyncClient:
    # The positional timeout covers read, write and pool acquisition; only connect
    # differs. For streamed responses "read" bounds the gap between two chunks,
    # not the whole response.
    timeout = httpx.Timeout(
        settings.upstream_read_timeout, connect=settings.upstream_connect_timeout
    )
    # A new client per request would pay for a fresh TLS handshake with OpenAI every time
    return httpx.AsyncClient(
        base_url=settings.openai_base_url,
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        timeout=timeout,
    )


@dataclass
class ProbeResult:
    ok: bool
    checked_at: float
    reason: str | None = None


class UpstreamProbe:
    """Answers "can we reach OpenAI with our key?", at most once per cache window."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._last: ProbeResult | None = None

    async def check(self) -> ProbeResult:
        if self._last is not None:
            age = time.monotonic() - self._last.checked_at
            if age < PROBE_CACHE_SECONDS:
                return self._last
        self._last = await self._probe()
        return self._last

    async def _probe(self) -> ProbeResult:
        now = time.monotonic()
        try:
            response = await self._client.get("/models", timeout=PROBE_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            reason = f"upstream unreachable: {type(exc).__name__}"
        else:
            if response.is_success:
                return ProbeResult(ok=True, checked_at=now)
            reason = f"upstream returned HTTP {response.status_code}"
        log.warning("upstream.probe_failed", extra={"reason": reason})
        return ProbeResult(ok=False, checked_at=now, reason=reason)


async def forward_chat_completion(
    client: httpx.AsyncClient, body: dict[str, Any], max_retries: int
) -> Response:
    stream = body.get("stream", False)
    started = time.perf_counter()
    response = await send_with_retries(client, body, stream, max_retries)
    if stream and response.is_success:
        return StreamingResponse(
            relay_stream(response, started),
            status_code=response.status_code,
            headers=SSE_HEADERS,
            media_type="text/event-stream",
        )
    log.info(
        "upstream.completed",
        extra={
            "status": response.status_code,
            "duration_ms": elapsed_ms(started),
            "openai_request_id": response.headers.get("x-request-id"),
        },
    )
    error = map_error_status(response.status_code)
    if error is not None:
        raise error
    return relay_response(response)


async def send_with_retries(
    client: httpx.AsyncClient, body: dict[str, Any], stream: bool, max_retries: int
) -> httpx.Response:
    # Everything here happens before any byte reaches the client. With
    # stream=True, send() returns as soon as OpenAI's headers arrive, and the
    # body is relayed later by relay_stream, which never retries.
    request = client.build_request("POST", "/chat/completions", json=body)
    attempt = 1
    while True:
        out_of_retries = attempt > max_retries
        log.info("upstream.request", extra={"attempt": attempt})
        try:
            response = await client.send(request, stream=stream)
            # Read error bodies in full now, so streamed and plain errors are
            # handled the same way from here on.
            if not response.is_success:
                await response.aread()
        except httpx.TransportError as exc:
            log.warning("upstream.failed", extra={"attempt": attempt, "error": type(exc).__name__})
            if out_of_retries:
                raise map_transport_error(exc) from exc
        else:
            if response.status_code < 500 or out_of_retries:
                return response
            log.warning(
                "upstream.failed", extra={"attempt": attempt, "status": response.status_code}
            )
        # sleep is imported by name so tests can swap it out and skip the real waits.
        await sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        attempt += 1


async def relay_stream(response: httpx.Response, started: float) -> AsyncIterator[bytes]:
    chunks = 0
    try:
        # aiter_bytes, not aiter_raw: if OpenAI compressed the stream, raw bytes
        # would reach the client still compressed. Neither one re-splits the
        # bytes, so SSE framing survives.
        async for chunk in response.aiter_bytes():
            if chunks == 0:
                log.info("upstream.first_byte", extra={"latency_ms": elapsed_ms(started)})
            chunks += 1
            yield chunk
    except httpx.TransportError as exc:
        log.error(
            "upstream.stream_interrupted",
            extra={
                "error": type(exc).__name__,
                "chunks": chunks,
                "duration_ms": elapsed_ms(started),
            },
        )
        yield stream_interrupted_event()
    except (CancelledError, GeneratorExit):
        # The client went away, for example because the user pressed stop. The
        # finally block closes the connection to OpenAI, which stops generation.
        log.info(
            "request.client_disconnected",
            extra={"chunks": chunks, "duration_ms": elapsed_ms(started)},
        )
        raise
    else:
        log.info(
            "upstream.completed",
            extra={
                "status": response.status_code,
                "duration_ms": elapsed_ms(started),
                "chunks": chunks,
                "openai_request_id": response.headers.get("x-request-id"),
            },
        )
    finally:
        await response.aclose()


def stream_interrupted_event() -> bytes:
    # The client already has a 200, so the error has to travel inside the
    # stream. The leading blank lines end any event the broken stream left
    # half-written.
    error = ErrorResponse(
        error=ErrorDetail(
            message="The upstream response was cut off.",
            type="upstream_error",
            code="upstream_stream_interrupted",
        )
    )
    return f"\n\ndata: {error.model_dump_json()}\n\ndata: [DONE]\n\n".encode()


def map_transport_error(exc: httpx.TransportError) -> ApiError:
    if isinstance(exc, httpx.TimeoutException):
        return ApiError(
            status_code=504,
            message="The upstream model provider did not respond in time.",
            error_type="upstream_error",
            code="upstream_timeout",
        )
    return ApiError(
        status_code=502,
        message="Could not reach the upstream model provider.",
        error_type="upstream_error",
        code="upstream_unreachable",
    )


def map_error_status(status_code: int) -> ApiError | None:
    # OpenAI's 401 message quotes part of our key, and neither 401 nor 403 is
    # something the end user can fix, so both become a generic 502.
    if status_code in (401, 403):
        return ApiError(
            status_code=502,
            message="Upstream authentication is misconfigured.",
            error_type="upstream_error",
            code="upstream_auth_misconfigured",
        )
    if status_code >= 500:
        return ApiError(
            status_code=502,
            message="The upstream model provider returned a server error.",
            error_type="upstream_error",
            code="upstream_server_error",
        )
    return None


def relay_response(response: httpx.Response) -> Response:
    # Retry-After is the one upstream header a client acts on: it says when a
    # rate-limited request may be sent again.
    headers = {}
    if "retry-after" in response.headers:
        headers["Retry-After"] = response.headers["retry-after"]
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=headers,
        media_type=response.headers.get("content-type"),
    )
