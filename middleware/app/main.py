import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth import require_api_key
from app.config import Settings
from app.logging import configure_logging, elapsed_ms, request_id_var
from app.prompt import load_system_prompt
from app.routes import chat, health, models
from app.schemas import ApiError, ErrorResponse
from app.upstream import UpstreamProbe, build_client

log = logging.getLogger(__name__)

# Docker polls these every few seconds; at INFO they would bury real traffic.
QUIET_PATHS = {"/health", "/ready"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = build_client(app.state.settings)
    app.state.http_client = client
    app.state.upstream_probe = UpstreamProbe(client)
    yield
    await client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    # if it fails, it fails here: we don't want to start the app if the system prompt is invalid
    system_prompt = load_system_prompt(settings.system_prompt_path)

    app = FastAPI(title="middleware", lifespan=lifespan)
    app.state.settings = settings
    app.state.system_prompt = system_prompt
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_middleware(RequestLifecycleMiddleware)
    app.include_router(health.router)
    app.include_router(models.router, dependencies=[Depends(require_api_key)])
    app.include_router(chat.router, dependencies=[Depends(require_api_key)])
    return app


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
    log.log(
        level,
        "request.failed",
        extra={"error_type": exc.detail.code, "mapped_status": exc.status_code},
    )
    body = ErrorResponse(error=exc.detail).model_dump()
    return JSONResponse(body, status_code=exc.status_code)


class RequestLifecycleMiddleware:
    # A plain ASGI middleware, not @app.middleware("http"). That style hands the
    # response back as soon as its headers exist, so for a stream it would log
    # request.completed before the answer had finished.
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Uvicorn also sends its startup and shutdown "lifespan" events through here.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get("x-request-id") or str(uuid.uuid4())
        # calls them every 10 seconds and they would bury real traffic
        level = logging.DEBUG if scope["path"] in QUIET_PATHS else logging.INFO
        # If the app crashes before it starts a response, the server answers 500.
        status = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        token = request_id_var.set(request_id)
        log.log(level, "request.received", extra={"method": scope["method"], "path": scope["path"]})
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            log.log(
                level,
                "request.completed",
                extra={"status": status, "duration_ms": elapsed_ms(started)},
            )
            request_id_var.reset(token)
