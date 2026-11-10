from pathlib import Path

import pytest

from app.prompt import PromptLoadError, extract_prompt, load_system_prompt
from tests.conftest import TEST_PROMPT


def test_extracts_text_between_markers() -> None:
    text = "intro\n<!-- PROMPT:BEGIN -->\n  hello  \n<!-- PROMPT:END -->\noutro"
    assert extract_prompt(text, source="x") == "hello"


def test_raises_when_markers_missing() -> None:
    with pytest.raises(PromptLoadError, match="must contain"):
        extract_prompt("no markers here", source="x")


def test_raises_when_prompt_is_empty() -> None:
    with pytest.raises(PromptLoadError, match="empty"):
        extract_prompt("<!-- PROMPT:BEGIN --> <!-- PROMPT:END -->", source="x")


def test_loads_from_file(prompt_file: Path) -> None:
    assert load_system_prompt(prompt_file) == TEST_PROMPT


def test_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(PromptLoadError, match="cannot read"):
        load_system_prompt(tmp_path / "nope.md")


def test_repository_prompt_file_loads() -> None:
    prompt = load_system_prompt(Path(__file__).parents[2] / "SYSTEM_PROMPT.md")

    assert prompt.startswith("You are a structured data extractor.")
    assert "PROMPT:" not in prompt
