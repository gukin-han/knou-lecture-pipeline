from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Provider
    llm_provider: Literal["anthropic", "openai"] = "anthropic"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Whisper
    whisper_model_size: str = "large-v3"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"

    # Pipeline
    chunk_size: int = Field(default=6000, ge=1000, le=20000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)

    # Data Paths
    input_dir: Path = Path("data/input")
    output_dir: Path = Path("data/output")
    intermediate_dir: Path = Path("data/intermediate")
    processed_dir: Path = Path("data/processed")
    failed_dir: Path = Path("data/failed")

    # Logging
    log_level: str = "INFO"
    log_file: Path = Path("logs/pipeline.log")

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        if v not in ("anthropic", "openai"):
            raise ValueError(f"llm_provider must be 'anthropic' or 'openai', got: {v}")
        return v

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        dirs = [
            self.input_dir,
            self.output_dir,
            self.intermediate_dir,
            self.processed_dir,
            self.failed_dir,
            self.log_file.parent,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def get_api_key(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key
        return self.openai_api_key

    def get_model(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        return self.openai_model


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
