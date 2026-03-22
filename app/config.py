from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./pdf_store.db"
    redis_url: str = "redis://localhost:6379/0"

    b2_access_key_id: str = ""
    b2_secret_access_key: str = ""
    b2_endpoint_url: str = ""   # e.g. https://s3.us-west-004.backblazeb2.com
    b2_bucket_name: str = "pdf-chunks"

    secret_key: str = "dev-only-secret"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
