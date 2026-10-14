import json
from typing import Annotated, Any

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors_origins(v: Any) -> list[str]:
    if isinstance(v, str):
        val = v.strip()
        if val.startswith("[") and val.endswith("]"):
            try:
                return json.loads(val)
            except Exception:
                pass
        return [origin.strip() for origin in val.split(",") if origin.strip()]
    elif isinstance(v, list | tuple):
        return [str(origin) for origin in v]
    return ["*"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = (
        "postgresql+psycopg://claimgraph:claimgraph@localhost:5432/claimgraph"
    )
    BACKEND_CORS_ORIGINS: Annotated[list[str], BeforeValidator(parse_cors_origins)] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    STORAGE_DIR: str = "./storage"
    LLM_PROVIDER: str = "groq"
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_EXTRACT_MODEL: str = "openai/gpt-oss-120b"
    LLM_CLASSIFY_MODEL: str = "openai/gpt-oss-20b"
    LLM_API_KEY: str = ""
    LLM_MODE: str = "replay"  # 'live' or 'replay'
    LLM_MAX_CONCURRENCY: int = 2


def get_settings() -> Settings:
    s = Settings()
    if not s.LLM_EXTRACT_MODEL:
        s.LLM_EXTRACT_MODEL = "openai/gpt-oss-120b"
    if not s.LLM_CLASSIFY_MODEL:
        s.LLM_CLASSIFY_MODEL = "openai/gpt-oss-20b"
    if not s.LLM_PROVIDER:
        s.LLM_PROVIDER = "groq"
    if not s.LLM_BASE_URL:
        s.LLM_BASE_URL = "https://api.groq.com/openai/v1"
    return s


settings = get_settings()


