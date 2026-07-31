from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    # How Pulse verifies identity's tokens: fetch the public keys from identity's
    # JWKS endpoint. The signing key never leaves identity (CLAUDE.md rule 4).
    IDENTITY_JWKS_URL: str = "http://identity:8000/.well-known/jwks.json"
    # Must match identity's JWT_ISSUER, or every token is rejected.
    JWT_ISSUER: str = "cyphercrescent-identity"
    JWKS_TTL_SECONDS: int = 3600
    CORS_ORIGINS: str = "http://localhost:3000"
    # Background jobs (Celery + Redis). REDIS_URL is broker + result backend.
    # SYNC_HOUR_UTC is the hour the daily GitHub sync fires (0-23, UTC).
    REDIS_URL: str = "redis://redis:6379/0"
    SYNC_HOUR_UTC: int = 2

    # ── GitHub OAuth + sync (Week 3) ──────────────────────────────────────
    # CLIENT_ID/SECRET come from the OAuth App. REDIRECT_URI must match the app's
    # "Authorization callback URL" exactly. TOKEN_ENC_KEY is a Fernet key used to
    # encrypt stored GitHub tokens at rest — required to connect a real account.
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8002/github/oauth/callback"
    GITHUB_OAUTH_SCOPES: str = "read:user"  # enough to identify the user + read public repos
    GITHUB_OAUTH_BASE: str = "https://github.com"  # authorize + token endpoints
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_TOKEN_ENC_KEY: str = ""
    # Which repos to sync: a whole org, and/or an explicit owner/name allowlist.
    GITHUB_ORG: str = ""
    GITHUB_REPOS: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def github_repos_list(self) -> list[str]:
        return [r.strip() for r in self.GITHUB_REPOS.split(",") if r.strip()]

settings = Settings()
