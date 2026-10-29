from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    data_dir: Path = BASE_DIR / "data"
    frontend_dir: Path = BASE_DIR.parent / "frontend" / "dist"
    model_config = SettingsConfigDict(
        env_prefix="NODEKIT_", env_file=BASE_DIR / ".envs" / ".local.env", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
