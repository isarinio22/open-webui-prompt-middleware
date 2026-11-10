from typing import Any

# Request bodies Open WebUI 0.6.5 sent to the middleware during real chats in
# its web UI, copied from the middleware's debug logs. A local stand-in played
# OpenAI, so the assistant reply in the history is its canned answer. Task
# prompts are cut after their first instruction line; detection reads only
# the start.

FIRST_TURN: dict[str, Any] = {
    "stream": True,
    "model": "gpt-4o-mini",
    "messages": [
        {
            "role": "user",
            "content": "Invoice #42 from ACME GmbH, dated 3 March 2026, total 99 EUR incl. 19% VAT.",
        }
    ],
}

TITLE_CALL: dict[str, Any] = {
    "model": "gpt-4o-mini",
    "messages": [
        {
            "role": "user",
            "content": "### Task:\nGenerate a concise, 3-5 word title with an emoji summarizing the chat history.",
        }
    ],
    "stream": False,
    "max_tokens": 1000,
}

TAGS_CALL: dict[str, Any] = {
    "model": "gpt-4o-mini",
    "messages": [
        {
            "role": "user",
            "content": "### Task:\nGenerate 1-3 broad tags categorizing the main themes of the chat history, along with 1-3 more specific subtopic tags.",
        }
    ],
    "stream": False,
}

SECOND_TURN: dict[str, Any] = {
    "stream": True,
    "model": "gpt-4o-mini",
    "messages": [
        {
            "role": "user",
            "content": "Invoice #42 from ACME GmbH, dated 3 March 2026, total 99 EUR incl. 19% VAT.",
        },
        {"role": "assistant", "content": "FAKE GPT. Extraction system prompt received first: yes."},
        {"role": "user", "content": "What was the VAT rate on that invoice?"},
    ],
}

WITH_USER_SYSTEM_PROMPT: dict[str, Any] = {
    "stream": True,
    "model": "gpt-4o-mini",
    "messages": [
        {"role": "system", "content": "Always answer in German."},
        {"role": "user", "content": "Receipt: 2 coffees, 7.40 EUR, Cafe Lisboa."},
    ],
}
