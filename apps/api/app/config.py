from functools import lru_cache

from exam_core.config import Settings


class ApiSettings(Settings):
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    # The refresh token is also sent as an httpOnly cookie for browser clients. Turn Secure off only
    # for plain-HTTP deployments without TLS (local dev on localhost works with Secure on).
    refresh_cookie_secure: bool = True

    # Where students open the join link: the web app's origin, no trailing slash.
    web_base_url: str = "http://localhost:5173"
    session_max_minutes: int = 480
    session_max_participants: int = 300

    exam_minutes_per_question: int = 2  # 65 questions -> 130 minutes
    exam_default_questions: int = 65
    practice_default_questions: int = 10


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()  # pyright: ignore[reportCallIssue]  # required fields come from env
