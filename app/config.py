from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    exam_minutes_per_question: int = 2  # 65 questions -> 130 minutes
    exam_default_questions: int = 65
    practice_default_questions: int = 10

    # Ingestion (M3)
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384 dims; see app.embeddings.EMBEDDING_DIM
    embedding_cache_dir: str = ".cache/fastembed"
    ingestion_allowed_hosts: list[str] = ["docs.aws.amazon.com", "aws.amazon.com"]
    fetch_timeout_seconds: float = 15
    fetch_max_bytes: int = 5_000_000
    fetch_max_redirects: int = 3
    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150

    database_url: str = "postgresql+psycopg://learn:learn@localhost:5432/learn_assistant"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env
