"""Settings shared by the API and the worker; the API adds its own on top (app.config)."""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Logging (API and worker). "text" is easier to read locally.
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # Login rate limiting (API): failed attempts per username / client IP in a sliding window.
    login_max_failures_per_username: int = 5
    login_max_failures_per_ip: int = 20
    login_window_seconds: int = 900
    # Number of trusted proxies (ALB = 1) in front of the API. 0: ignore X-Forwarded-For.
    trusted_proxy_hops: int = 0

    # Ingestion (worker)
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384 dims; see exam_core.embeddings.EMBEDDING_DIM
    embedding_cache_dir: str = "../../.cache/fastembed"  # repo root; the API and worker run from apps/*
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
    local_storage_dir: str = "../../.data/documents"  # shared by the API (writes) and the worker (reads)
    s3_bucket: str | None = None
    s3_prefix: str = "documents/"
    upload_max_bytes: int = 25_000_000
    pdf_max_pages: int = 400
    pdf_chunk_max_lines: int = 40  # lines per chunk, a chunk never spans a document boundary
    pdf_chunk_overlap_lines: int = 5
    job_stale_minutes: int = 30  # a job still running after this long is reported as failed

    # Job queue. The API sends, the worker receives. In development this points at ElasticMQ
    # (an SQS-compatible container, see compose.yaml); on AWS the queue URL comes from Terraform.
    sqs_queue_url: str | None = None
    sqs_endpoint_url: str | None = None  # only for local SQS emulators
    sqs_region: str = "us-east-1"
    worker_visibility_seconds: int = 300  # how long a received message stays hidden; extended while working

    # LLM (generation + blind validation), used by the worker. Generation fails while the key is unset.
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
    return Settings()
