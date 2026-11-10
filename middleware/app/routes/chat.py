import logging
from typing import Any

from fastapi import APIRouter, Request, Response

from app.config import Settings
from app.injection import (
    Message,
    inject_system_prompt,
    is_internal_task,
    starts_with_system_prompt,
)
from app.schemas import ApiError, ChatCompletionRequest
from app.upstream import forward_chat_completion

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    body = await read_chat_body(request)
    log.info("chat.request", extra=describe_chat(body, settings.log_message_content))
    require_allowed_model(body["model"], settings.allowed_models)
    messages = messages_to_forward(
        body, request.app.state.system_prompt, settings.inject_on_internal_tasks
    )
    return await forward_chat_completion(
        request.app.state.http_client,
        {**body, "messages": messages},
        settings.upstream_max_retries,
    )


async def read_chat_body(request: Request) -> dict[str, Any]:
    # The schema only validates. The original dict is what gets forwarded, so
    # fields the schema does not declare still reach OpenAI unchanged.
    try:
        body = await request.json()
        ChatCompletionRequest.model_validate(body)
    # Bad JSON, bad UTF-8 and a wrong shape all raise ValueError subclasses.
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            message="Request body must be a JSON object with 'model' and 'messages'.",
            error_type="invalid_request_error",
            code="invalid_body",
        ) from exc
    return body


def require_allowed_model(model: str, allowed_models: list[str]) -> None:
    # Same status, type and code OpenAI uses for a model that doesn't exist, so
    # Open WebUI shows its usual message.
    if model not in allowed_models:
        raise ApiError(
            status_code=404,
            message=f"The model '{model}' is not available through this middleware.",
            error_type="invalid_request_error",
            code="model_not_found",
        )


def describe_chat(body: dict[str, Any], include_content: bool) -> dict[str, Any]:
    messages = body["messages"]
    fields: dict[str, Any] = {
        "model": body["model"],
        "stream": body.get("stream", False),
        "message_count": len(messages),
        "has_client_system_message": any(m.get("role") == "system" for m in messages),
    }
    if include_content:
        fields["messages"] = messages
    return fields


def messages_to_forward(
    body: dict[str, Any], prompt: str, inject_on_internal_tasks: bool
) -> list[Message]:
    messages = body["messages"]
    if is_internal_task(body) and not inject_on_internal_tasks:
        log.info("injection.skipped", extra={"reason": "internal_task"})
        return messages
    if starts_with_system_prompt(messages, prompt):
        log.info("injection.skipped", extra={"reason": "already_present"})
        return messages
    log.info("injection.applied")
    return inject_system_prompt(messages, prompt)
