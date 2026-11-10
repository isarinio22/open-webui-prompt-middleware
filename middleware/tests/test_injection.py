import copy
from typing import Any

import pytest

from app.injection import inject_system_prompt, is_internal_task
from tests import recorded

PROMPT = "You extract data."
OURS = {"role": "system", "content": PROMPT}
TITLE_TASK = recorded.TITLE_CALL["messages"][0]["content"]


def test_prepends_system_prompt() -> None:
    messages = [{"role": "user", "content": "hi"}]

    assert inject_system_prompt(messages, PROMPT) == [OURS, {"role": "user", "content": "hi"}]


def test_keeps_client_system_message_after_ours() -> None:
    messages = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]

    assert inject_system_prompt(messages, PROMPT) == [OURS, *messages]


def test_is_idempotent() -> None:
    once = inject_system_prompt([{"role": "user", "content": "hi"}], PROMPT)

    assert inject_system_prompt(once, PROMPT) == once


def test_handles_empty_list() -> None:
    assert inject_system_prompt([], PROMPT) == [OURS]


def test_leaves_multimodal_content_untouched() -> None:
    parts = [
        {"type": "text", "text": "What is on this receipt?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    messages = [{"role": "user", "content": parts}]

    result = inject_system_prompt(messages, PROMPT)

    assert result[1] == {"role": "user", "content": parts}


def test_does_not_mutate_input() -> None:
    messages = [{"role": "user", "content": "hi"}]
    snapshot = copy.deepcopy(messages)

    inject_system_prompt(messages, PROMPT)

    assert messages == snapshot


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            {"messages": [{"role": "user", "content": TITLE_TASK}]},
            True,
            id="stream_omitted_means_false",
        ),
        pytest.param(
            {"stream": True, "messages": [{"role": "user", "content": TITLE_TASK}]},
            False,
            id="streaming_is_never_a_task",
        ),
        pytest.param(
            {
                "stream": False,
                "messages": [{"role": "user", "content": "What does ### Task: mean?"}],
            },
            False,
            id="prefix_not_at_start",
        ),
        pytest.param(
            {
                "stream": False,
                "messages": [
                    {"role": "user", "content": TITLE_TASK},
                    {"role": "assistant", "content": "Invoice summary"},
                    {"role": "user", "content": "thanks"},
                ],
            },
            False,
            id="only_last_user_message_counts",
        ),
        pytest.param(
            {
                "stream": False,
                "messages": [{"role": "user", "content": [{"type": "text", "text": TITLE_TASK}]}],
            },
            False,
            id="multimodal_content",
        ),
        pytest.param(
            {"stream": False, "messages": [{"role": "system", "content": TITLE_TASK}]},
            False,
            id="no_user_message",
        ),
    ],
)
def test_detects_internal_task(body: dict[str, Any], expected: bool) -> None:
    assert is_internal_task(body) is expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(recorded.FIRST_TURN, False, id="first_turn"),
        pytest.param(recorded.TITLE_CALL, True, id="title_call"),
        pytest.param(recorded.TAGS_CALL, True, id="tags_call"),
        pytest.param(recorded.SECOND_TURN, False, id="second_turn"),
        pytest.param(recorded.WITH_USER_SYSTEM_PROMPT, False, id="user_system_prompt"),
    ],
)
def test_classifies_recorded_open_webui_requests(body: dict[str, Any], expected: bool) -> None:
    assert is_internal_task(body) is expected
