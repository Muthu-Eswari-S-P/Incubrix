from connectors import router
from fastapi import FastAPI


app = FastAPI(
    title="IncuBrix Distribution Service",
    version="1.0.0",
    description="Long-tail content distribution and connector service"
)
app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"status": "ready"}


@app.get("/api/v1/")
def home():
    return {
        "service": "IncuBrix Distribution Service",
        "version": "1.0.0",
        "message": "API is running"
    }
