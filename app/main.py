from fastapi import APIRouter, FastAPI

from app.auth import router as auth_router
from app.users import router as users_router

app = FastAPI(title="learn-assistant")

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth_router)
api_v1.include_router(users_router)
app.include_router(api_v1)


@app.get("/health")
def health():
    return {"status": "ok"}
