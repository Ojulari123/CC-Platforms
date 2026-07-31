from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routes import activity, github, health, reports, repositories

app = FastAPI(title="Crescent Pulse", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(reports.router)
app.include_router(github.router)
app.include_router(repositories.router)
app.include_router(activity.router)

@app.get("/")
def root():
    return {"service": "pulse", "status": "ok"}
