from fastapi import FastAPI

app = FastAPI(title="learn-assistant")


@app.get("/health")
def health():
    return {"status": "ok"}
