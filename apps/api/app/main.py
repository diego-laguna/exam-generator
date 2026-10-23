from typing import Any

from exam_core.logging import configure_logging
from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from app.auth import router as auth_router
from app.documents import router as documents_router
from app.config import get_settings
from app.errors import ERROR_RESPONSES, install_error_handling
from app.exam_sessions import join_router, teacher_router as exam_sessions_router
from app.exams import router as exams_router
from app.generations import router as generations_router
from app.question_sets import router as question_sets_router
from app.questions import router as questions_router
from app.sources import router as sources_router
from app.stats import router as stats_router
from app.users import router as users_router

DESCRIPTION = """
Teachers upload PDFs and the API generates multiple-choice and true/false questions that cite
file, page and line. Teachers save question sets and download printable PDFs. A smaller student
module offers timed exams and practice sessions.

**Sign in:** call `POST /api/v1/auth/login`, or use the **Authorize** button with a username and
password. Each endpoint below says who may call it and gives a **Use case** example.
"""

TAGS = [
    {"name": "auth", "description": "Sign in, rotate tokens, sign out."},
    {"name": "users", "description": "Account creation (admin)."},
    {"name": "documents", "description": "Teacher PDFs: upload, status, delete."},
    {"name": "generations", "description": "Background jobs that generate cited questions."},
    {"name": "questions", "description": "The teacher's generated question bank."},
    {"name": "question-sets", "description": "Saved selections of questions and their printable PDFs."},
    {"name": "exam-sessions", "description": "Teacher: download the built-in exam, open timed sessions, watch the results dashboard."},
    {"name": "join", "description": "Students (no account): open a session link, answer, submit, see the result."},
    {"name": "exams", "description": "Student exams and practice sessions."},
    {"name": "stats", "description": "Student accuracy by domain."},
    {"name": "sources", "description": "Admin: AWS documentation sources and sample questions."},
    {"name": "health", "description": "Liveness probe."},
]

configure_logging(get_settings().log_level, get_settings().log_format)

app = FastAPI(
    title="Exam-Generator API",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    responses=ERROR_RESPONSES,  # declaring 422 also replaces FastAPI's default HTTPValidationError
)
install_error_handling(app)


def custom_openapi() -> dict[str, Any]:
    """Error responses are application/problem+json (FastAPI documents a model as application/json)."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description, routes=app.routes, tags=TAGS
    )
    for path in schema["paths"].values():
        for operation in path.values():
            for code, response in operation["responses"].items():
                if code in ("4XX", "5XX") or (code.isdigit() and int(code) >= 400):
                    content = response.get("content", {})
                    if "application/json" in content:
                        content["application/problem+json"] = content.pop("application/json")
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

def health():
    """Liveness probe. Public, no sign-in needed.

    **Use case:** the load balancer calls `GET /health` every few seconds, and the web app shows
    the same answer from `GET /api/v1/health` as its API status dot.
    """
    return {"status": "ok"}


api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth_router)
api_v1.include_router(users_router)
api_v1.include_router(sources_router)
api_v1.include_router(exams_router)
api_v1.include_router(stats_router)
api_v1.include_router(documents_router)
api_v1.include_router(generations_router)
api_v1.include_router(questions_router)
api_v1.include_router(question_sets_router)
api_v1.include_router(exam_sessions_router)
api_v1.include_router(join_router)
# Also under /api/v1, so a browser app that only reaches /api/* (one origin, as behind a proxy)
# can show whether the API is up. The unversioned /health below is for load balancers and probes.
api_v1.get("/health", tags=["health"])(health)
app.include_router(api_v1)

app.get("/health")(health)
