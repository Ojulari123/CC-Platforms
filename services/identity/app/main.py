from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.db import SessionLocal
from app.rate_limit import limiter
from app.routes import auth, departments, health, internal, invites, jwks, me, oauth, platform, teams
from app.services import service_clients as service_client_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Provision the Pulse service client if a secret is configured. Guarded so an
    unconfigured environment (import check, CI, fresh dev) boots without a DB write
    and never crashes on a missing secret."""
    db = SessionLocal()
    try:
        service_client_service.seed_pulse_client(db)
    finally:
        db.close()
    yield

app = FastAPI(title="Crescent Identity", version="0.0.1", lifespan=lifespan)

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
app.include_router(jwks.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(departments.router)
app.include_router(teams.router)
app.include_router(teams.flat_router)
app.include_router(platform.router)
app.include_router(platform.accounts_router)
app.include_router(invites.router)
app.include_router(oauth.router)
app.include_router(internal.router)

@app.get("/")
def root():
    return {"service": "identity", "status": "ok"}
