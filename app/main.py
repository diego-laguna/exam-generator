from fastapi import FastAPI

from app.auth import router as auth_router

app = FastAPI(title="learn-assistant")
app.include_router(auth_router)


@app.get("/health")
def health():
    return {"status": "ok"}
