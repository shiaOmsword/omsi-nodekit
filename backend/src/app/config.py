import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parents[2]
ENVIRONMENT = os.getenv("APP_ENV", "local")
ENV_FILE = BASE_DIR / ".envs" / f".env.{ENVIRONMENT}."

class Settings(BaseSettings):
    environment: str = Field(default=ENVIRONMENT, alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    
    config_dir: Path = BASE_DIR / "config"

    model_config = SettingsConfigDict(
        env_file=f"{ENV_FILE}",
        env_file_encoding="utf-8",
        extra="ignore",
        populateby_name=True,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()