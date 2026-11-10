from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    # Config and prompt are loaded in create_app, so a running process already has
    # both. The only thing that can change at runtime is the upstream.
    result = await request.app.state.upstream_probe.check()
    if result.ok:
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not_ready", "reason": result.reason}, status_code=503)
