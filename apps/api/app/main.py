from fastapi import APIRouter, FastAPI

from app.auth import router as auth_router
from app.documents import router as documents_router
from app.exams import router as exams_router
from app.generations import router as generations_router
from app.question_sets import router as question_sets_router
from app.questions import router as questions_router
from app.sources import router as sources_router
from app.stats import router as stats_router
from app.users import router as users_router

app = FastAPI(title="Exam-Generator API")

def health():
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
# Also under /api/v1, so a browser app that only reaches /api/* (one origin, as behind a proxy)
# can show whether the API is up. The unversioned /health below is for load balancers and probes.
api_v1.get("/health", tags=["health"])(health)
app.include_router(api_v1)

app.get("/health")(health)
