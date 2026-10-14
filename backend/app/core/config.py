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
    LLM_EXTRACT_MODEL: str = ""
    LLM_CLASSIFY_MODEL: str = ""
    LLM_API_KEY: str = ""


settings = Settings()
