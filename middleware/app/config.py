from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # Compose passes unset variables as empty strings; treat those as "not set".
    model_config = SettingsConfigDict(env_ignore_empty=True)

    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    # pydantic-settings decodes list fields as JSON by default; NoDecode turns that
    # off so the validator below can accept the plain "a,b,c" form.
    allowed_models: Annotated[list[str], NoDecode] = ["gpt-4o-mini", "gpt-4o"]
    system_prompt_path: Path = Path("/app/SYSTEM_PROMPT.md")
    middleware_api_key: str | None = None
    inject_on_internal_tasks: bool = False
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 60.0
    upstream_max_retries: int = 2
    log_level: str = "INFO"
    log_message_content: bool = False

    @field_validator("allowed_models", mode="before")
    @classmethod
    def split_comma_separated(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
