from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_prefix="NOSTOS_", 
        extra="ignore"
    )

    # App
    app_name: str = "Nostos API"
    host: str = "127.0.0.1"
    port: int = 3072
    reload: bool = True

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_job_ttl_seconds: int = 60 * 60 * 24

    # Postgres
    postgres_url: str = "postgresql://postgres:postgres@localhost:5432/nostos"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"

    # CORS
    allowed_origins: list[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]

    # LLMs
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5"
    openai_api_key: str = ""
    gpt_model: str = "gpt-5.6-luna"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct"

    # Email
    resend_api_key: str = ""
    email_from_address: str = "Nostos <onboarding@resend.dev>"

    # SerpAPI
    serpapi_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()