from typing import Any, Literal

from pydantic import BaseModel


# match OpenAI's error format
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


# match OpenAI's model list format
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
    stream: bool = False
