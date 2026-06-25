from fastapi import FastAPI

app = FastAPI(title="Cartright")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
