from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.db import SessionLocal
from app.rate_limit import limiter
from app.routes import datasets, health
from app.services.datasets import seed_sample_datasets

@asynccontextmanager
async def lifespan(app: FastAPI):
    # seed_sample_datasets is idempotent, so re-running it on every boot is safe.
    db = SessionLocal()
    try:
        seed_sample_datasets(db)
    finally:
        db.close()
    yield

app = FastAPI(title="Crescent Forge", version="0.0.1", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(datasets.router)

@app.get("/")
def root():
    return {"service": "forge", "status": "ok"}
