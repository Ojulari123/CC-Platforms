from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routes import auth, health, jwks, me

app = FastAPI(title="Crescent Identity", version="0.0.1")

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

@app.get("/")
def root():
    return {"service": "identity", "status": "ok"}
