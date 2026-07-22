from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.rate_limit import limiter
from app.routes import auth, health, invites, jwks, me, orgs

app = FastAPI(title="Crescent Identity", version="0.0.1")

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
app.include_router(orgs.router)
app.include_router(invites.router)

@app.get("/")
def root():
    return {"service": "identity", "status": "ok"}
