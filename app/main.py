from fastapi import FastAPI

app = FastAPI(title="learn-assistant")


@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI"}
