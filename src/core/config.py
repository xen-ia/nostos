from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NOSTOS_", extra="ignore")

    # App
    app_name: str = "Nostos API"
    app_version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 3072
    reload: bool = True

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_job_ttl_seconds: int = 60 * 60 * 24  # 24h

    # CORS
    allowed_origins: list[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]


# Singletoness
@lru_cache
def get_settings() -> Settings:
    return Settings()