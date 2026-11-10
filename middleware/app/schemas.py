from typing import Any, Literal

from pydantic import BaseModel, StrictBool


# OpenAI's error format, which Open WebUI knows how to display.
class ErrorDetail(BaseModel):
    message: str
    type: str
    code: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    """Raised anywhere in a request; rendered as an OpenAI-shaped error by main.py."""

    def __init__(self, status_code: int, message: str, error_type: str, code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = ErrorDetail(message=message, type=error_type, code=code)


# OpenAI's model list format, returned by GET /v1/models.
class ModelObject(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "openai"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    # Strict, so a string such as "false" is rejected instead of being read as
    # true. OpenAI also accepts null, meaning not streamed.
    stream: StrictBool | None = None
