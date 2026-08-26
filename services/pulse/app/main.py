from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.crypto import TokenEncryptionNotConfigured
from app.models import EMBEDDING_DIM
from app.rate_limit import limiter
from app.routes import activity, admin, chat, credentials, github, health, journals, personas, repo_index, reports, repositories

# Fail here rather than at query time: an embedding of the wrong width is rejected by
# Postgres per-row, mid-ingest, after the tokens have already been paid for.
if settings.EMBEDDING_DIMENSIONS != EMBEDDING_DIM:
    raise RuntimeError(
        f"EMBEDDING_DIMENSIONS is {settings.EMBEDDING_DIMENSIONS} but repo_chunks.embedding is "
        f"{EMBEDDING_DIM} wide. The column width is fixed by migration 0008 and cannot be changed "
        f"by configuration; set EMBEDDING_DIMENSIONS={EMBEDDING_DIM} (the width of "
        f"text-embedding-3-small), or migrate the column to a new width."
    )

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
app.include_router(journals.router)
app.include_router(repo_index.router)
app.include_router(chat.router)
app.include_router(activity.router)
app.include_router(personas.router)
app.include_router(credentials.router)
app.include_router(admin.router)

@app.get("/")
def root():
    return {"service": "pulse", "status": "ok"}
