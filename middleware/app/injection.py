from typing import Any

Message = dict[str, Any]

# Open WebUI 0.6.5 sends its title and tag requests as one non-streamed user
# message that starts with this line. It strips its own task label before
# forwarding, so the text is the only signal the middleware gets.
TASK_PREFIX = "### Task:"


def inject_system_prompt(messages: list[Message], prompt: str) -> list[Message]:
    if starts_with_system_prompt(messages, prompt):
        return list(messages)
    return [{"role": "system", "content": prompt}, *messages]


def starts_with_system_prompt(messages: list[Message], prompt: str) -> bool:
    if not messages:
        return False
    first = messages[0]
    return first.get("role") == "system" and first.get("content") == prompt


def is_internal_task(body: dict[str, Any]) -> bool:
    if body.get("stream", False):
        return False
    user_messages = [m for m in body["messages"] if m.get("role") == "user"]
    if not user_messages:
        return False
    content = user_messages[-1].get("content")
    # Multimodal content is a list of parts. Open WebUI's task prompts are plain strings.
    return isinstance(content, str) and content.startswith(TASK_PREFIX)
