"""Settings loaded from the environment and .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Region = Literal["us", "eu", "kr", "tw"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bnet_client_id: str = ""
    bnet_client_secret: SecretStr = SecretStr("")
    bnet_region: Region = "us"
    bnet_redirect_uri: str = "http://localhost:8000/auth/callback"

    character_name: str = "Brumboldt"
    character_surname: str = "Doomlet"

    database_url: str = "sqlite:///data/character-planner.db"
    curated_dir: Path = Path("data/curated")

    @property
    def api_base_url(self) -> str:
        return f"https://{self.bnet_region}.api.blizzard.com"

    @property
    def profile_namespace(self) -> str:
        # Undocumented; found by community probing after the 2026-11-04 launch.
        return f"profile-forever-{self.bnet_region}"

    @property
    def character_slug(self) -> str:
        # Forever character routes use {name}-{surname}, lowercase.
        return f"{self.character_name}-{self.character_surname}".lower()

    @property
    def has_credentials(self) -> bool:
        return bool(self.bnet_client_id and self.bnet_client_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
