from pathlib import Path

BEGIN_MARKER = "<!-- PROMPT:BEGIN -->"
END_MARKER = "<!-- PROMPT:END -->"


class PromptLoadError(RuntimeError):
    pass


def load_system_prompt(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptLoadError(f"cannot read system prompt file {path}: {exc}") from exc
    return extract_prompt(text, source=str(path))


def extract_prompt(text: str, source: str) -> str:
    begin = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if begin == -1 or end == -1 or end < begin:
        raise PromptLoadError(f"{source} must contain {BEGIN_MARKER} ... {END_MARKER}")
    prompt = text[begin + len(BEGIN_MARKER) : end].strip()
    if not prompt:
        raise PromptLoadError(f"system prompt between markers in {source} is empty")
    return prompt
