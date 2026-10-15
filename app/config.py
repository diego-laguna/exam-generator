from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Single built-in user until a real user store exists.
    auth_username: str
    auth_password_hash: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
