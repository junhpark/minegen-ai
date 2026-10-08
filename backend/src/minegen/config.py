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
    demos_autobake: bool = Field(
        default=True,
        description=(
            "PR #54 review B1: bake the demo mines that the catalogue does not list as "
            "available in a background thread at application startup "
            "(services/demo_materializer.py). Off in the test suite, the browser e2e and "
            "the baker's own application (MINEGEN_DEMOS_AUTOBAKE=0)."
        ),
    )

    @property
    def scenarios_dir(self) -> Path:
        return self.data_dir / "scenarios"

    @property
    def demos_dir(self) -> Path:
        """Hardening PR-2 H4: the baked, READ-ONLY demo mines
        (``data/demos/{id}/`` + ``data/demos/index.json``, written only by the
        demo baker — ``scripts/bake_demos.py`` and, PR #54 review B1, the
        automatic materialization at startup / dev-setup). The scenario store
        resolves a demo id here when no saved scenario carries it, and refuses
        every write to it."""
        return self.data_dir / "demos"


@lru_cache
def get_settings() -> Settings:
    return Settings()
