import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth import require_api_key
from app.config import Settings
from app.logging import configure_logging, elapsed_ms, request_id_var
from app.prompt import load_system_prompt
from app.routes import chat, health, models
from app.schemas import ApiError, ErrorDetail, ErrorResponse
from app.upstream import UpstreamProbe, build_client

log = logging.getLogger(__name__)

# Docker polls these every 10 seconds; at INFO they would bury real traffic.
QUIET_PATHS = {"/health", "/ready"}

INTERNAL_ERROR = ErrorDetail(
    message="The middleware failed unexpectedly.", type="server_error", code="internal_error"
)


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
    # Fails fast: the app must not start without a valid system prompt.
    system_prompt = load_system_prompt(settings.system_prompt_path)

    app = FastAPI(title="middleware", lifespan=lifespan)
    app.state.settings = settings
    app.state.system_prompt = system_prompt
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
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
        extra={
            "error_type": exc.detail.type,
            "error_code": exc.detail.code,
            "mapped_status": exc.status_code,
        },
    )
    body = ErrorResponse(error=exc.detail).model_dump()
    return JSONResponse(body, status_code=exc.status_code)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Routing errors such as an unknown path (404) or a wrong method (405), which
    # FastAPI would otherwise answer as {"detail": ...}.
    error = ApiError(
        status_code=exc.status_code,
        message=str(exc.detail),
        error_type="invalid_request_error",
        code=HTTPStatus(exc.status_code).name.lower(),
    )
    response = await api_error_handler(request, error)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


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
        level = logging.DEBUG if scope["path"] in QUIET_PATHS else logging.INFO
        status: int | None = None
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
        except Exception:
            # Anticipated errors never get here: they are ApiError or HTTPException
            # and already became responses. This is a bug, logged with its traceback.
            log.exception(
                "request.failed",
                extra={
                    "error_type": "server_error",
                    "error_code": "internal_error",
                    "mapped_status": 500,
                },
            )
            if status is not None:
                # Part of the response is already sent, so its status can't change.
                raise
            # A Starlette response is itself an ASGI app, so it can send itself.
            response = JSONResponse(
                ErrorResponse(error=INTERNAL_ERROR).model_dump(), status_code=500
            )
            await response(scope, receive, send_with_request_id)
        finally:
            log.log(
                level,
                "request.completed",
                extra={"status": status, "duration_ms": elapsed_ms(started)},
            )
            request_id_var.reset(token)
