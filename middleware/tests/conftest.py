import io
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.config import Settings
from app.logging import JsonFormatter
from app.main import create_app

UPSTREAM_BASE_URL = "https://upstream.test/v1"
UPSTREAM_API_KEY = "sk-test-secret-do-not-log"
TEST_PROMPT = "You are a test prompt."

CHAT_BODY: dict[str, Any] = {
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Invoice #42, total 99 EUR"}],
}
COMPLETION: dict[str, Any] = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Invoice"},
            "finish_reason": "stop",
        }
    ],
}


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    path = tmp_path / "SYSTEM_PROMPT.md"
    path.write_text(
        f"# Doc\n\nExplanation.\n\n<!-- PROMPT:BEGIN -->\n{TEST_PROMPT}\n<!-- PROMPT:END -->\n"
    )
    return path


@pytest.fixture(autouse=True)
def backoff_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # Retries wait between attempts. Every test records the waits instead of
    # sleeping, and a test that cares can ask for this list.
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("app.upstream.sleep", record)
    return waits


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    # A test changes one setting with
    # @pytest.mark.parametrize("settings_overrides", [{...}]),
    # which replaces this fixture's value for that test.
    return {}


@pytest.fixture
def settings(prompt_file: Path, settings_overrides: dict[str, Any]) -> Settings:
    return Settings(
        openai_api_key=UPSTREAM_API_KEY,
        openai_base_url=UPSTREAM_BASE_URL,
        system_prompt_path=prompt_file,
        **settings_overrides,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport does not send lifespan events, so enter the lifespan by hand;
    # otherwise the upstream client is never created.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
            yield c


@pytest.fixture
def upstream() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=UPSTREAM_BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def log_lines(app: FastAPI) -> Iterator[Callable[[], list[dict[str, object]]]]:
    # Capture what the JSON formatter actually writes, not the raw records, so the
    # tests see exactly what an operator would see on stdout.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    root.removeHandler(handler)
