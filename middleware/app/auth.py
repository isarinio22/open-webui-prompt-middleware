import hmac

from fastapi import Request

from app.schemas import ApiError


async def require_api_key(request: Request) -> None:
    expected: str | None = request.app.state.settings.middleware_api_key
    if expected is None:
        return
    provided = request.headers.get("authorization", "")
    if not hmac.compare_digest(provided.encode(), f"Bearer {expected}".encode()):
        raise ApiError(
            status_code=401,
            message="Invalid or missing API key.",
            error_type="invalid_request_error",
            code="invalid_api_key",
        )
