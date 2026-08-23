"""Application configuration.

All settings can be overridden with environment variables prefixed ``MINEGEN_``,
e.g. ``MINEGEN_DATA_DIR=/data``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CANONICAL_COORDINATE_SYSTEM = "ENU_Z_UP"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINEGEN_", env_file=".env", extra="ignore")

    app_name: str = "MineGen-AI"
    version: str = "0.1.0"
    data_dir: Path = Field(
        default=Path(__file__).resolve().parents[3] / "data",
        description="Root for on-disk scenario storage (data/scenarios/{id}/).",
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def scenarios_dir(self) -> Path:
        return self.data_dir / "scenarios"


@lru_cache
def get_settings() -> Settings:
    return Settings()
