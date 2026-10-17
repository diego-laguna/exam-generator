from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr, field_validator
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
    # Alternative to DATABASE_URL for AWS: ECS injects the RDS secret's fields separately.
    # When db_host is set, the URL is built from these parts (password is URL-escaped).
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "learn_assistant"
    db_user: str = "learn"
    db_password: SecretStr | None = None

    # Teacher PDFs
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = ".data/documents"
    s3_bucket: str | None = None
    s3_prefix: str = "documents/"
    upload_max_bytes: int = 25_000_000
    pdf_max_pages: int = 400
    pdf_chunk_max_lines: int = 40  # lines per chunk, a chunk never spans a document boundary
    pdf_chunk_overlap_lines: int = 5
    job_stale_minutes: int = 30  # a job still running after this long is reported as failed

    # LLM (generation + blind validation). Generation is disabled while the key is unset.
    anthropic_api_key: SecretStr | None = None
    llm_generation_model: str = "claude-sonnet-5-5"
    llm_validation_model: str = "claude-sonnet-5-5"
    llm_max_tokens: int = 2000
    generation_max_questions: int = 50
    generation_attempts_per_slot: int = 3

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_unset(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def sqlalchemy_url(self) -> str:
        if self.db_host is None:
            return self.database_url
        password = quote(self.db_password.get_secret_value(), safe="") if self.db_password else ""
        return (
            f"postgresql+psycopg://{quote(self.db_user, safe='')}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env
