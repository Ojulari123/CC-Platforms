from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.crypto import TokenEncryptionNotConfigured
from app.rate_limit import limiter
from app.routes import activity, admin, github, health, reports, repositories

app = FastAPI(title="Crescent Pulse", version="0.0.1")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(TokenEncryptionNotConfigured)
def token_encryption_not_configured(request: Request, exc: TokenEncryptionNotConfigured) -> JSONResponse:
    """Backstop for any route that reaches the encryption key without going through the
    OAuth pre-check. crypto.py has already logged which variable is missing."""
    return JSONResponse(
        status_code=503,
        content={"detail": "GitHub is not set up on this server. Contact an admin."},
    )

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
app.include_router(admin.router)

@app.get("/")
def root():
    return {"service": "pulse", "status": "ok"}
