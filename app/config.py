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

    database_url: str = "postgresql+psycopg://learn:learn@localhost:5432/learn_assistant"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env
