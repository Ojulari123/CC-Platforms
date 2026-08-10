import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.db import SessionLocal
from app.rate_limit import limiter
from app.routes import auth, departments, health, internal, invites, jwks, me, oauth, platform, teams
from app.security import keys as key_material
from app.services import service_clients as service_client_service

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keys are read once, here: a malformed one fails the deploy loudly rather than
    # 500ing /.well-known/jwks.json later. See README "Signing keys and rotation".
    retired_kids = key_material.validate_retired_public_keys()
    if len(retired_kids) >= key_material.RETIRED_KEY_WARN_THRESHOLD:
        logger.warning(
            "%d retired signing keys are being published at /.well-known/jwks.json. Each one is "
            "served on every fetch, and a retired key is only needed until the last token it "
            "signed expires (minutes). Prune them: scripts/rotate-identity-keys.sh prune",
            len(retired_kids),
        )
    if not settings.signup_allowed_domains_list:
        # An empty allowlist means POST /auth/signup accepts ANY address. That is
        # the intended dev default, but it fails open, so say so out loud.
        logger.warning(
            "SIGNUP_ALLOWED_DOMAINS is empty — self-signup at POST /auth/signup is OPEN to any "
            "email address on the internet. Set SIGNUP_ALLOWED_DOMAINS (e.g. cyphercrescent.com) "
            "before deploying anywhere non-local."
        )
    db = SessionLocal()
    try:
        service_client_service.seed_pulse_client(db)
        service_client_service.seed_forge_client(db)
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
