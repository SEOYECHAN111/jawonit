from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "자원잇다 운영 백엔드"
    app_env: str = "local"
    secret_key: str = "CHANGE_ME"
    cors_origins: str = "*"

    database_url: str = "sqlite:///./storage/jawonitda.db"

    object_storage_mode: str = "local"
    local_upload_dir: str = "./storage/uploads"

    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "auto"
    s3_public_base_url: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
