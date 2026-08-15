from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Counts hops from the RIGHT of X-Forwarded-For; below 1 reads a caller-supplied entry.
MIN_TRUSTED_PROXY_COUNT = 1

# Managed Postgres providers (Render's fromDatabase wiring, Heroku, Neon's copy
# button) hand out URLs on these schemes. SQLAlchemy reads a bare postgresql://
# as "use psycopg2", which is not in requirements.txt, so the app would fail to
# boot on a URL nobody typed wrong. Rewritten to the psycopg 3 driver we ship.
DRIVERLESS_POSTGRES_SCHEMES = ("postgresql://", "postgres://")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)

    DATABASE_URL: str
    IDENTITY_JWKS_URL: str = "http://identity:8000/.well-known/jwks.json"

    IDENTITY_API_URL: str = "http://identity:8000"
    PULSE_SERVICE_CLIENT_ID: str = "pulse"
    PULSE_SERVICE_CLIENT_SECRET: str = ""

    JWT_ISSUER: str = "cyphercrescent-identity"
    JWKS_TTL_SECONDS: int = 3600
    TOKEN_VERSION_TTL_SECONDS: int = 60
    # Forge 3000, Pulse's own frontend 3001, identity's admin UI 3002 — identity's product
    # picker reads live counts straight from Pulse, so its origin has to be on the list.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002"

    RATE_LIMIT_ENABLED: bool = True
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_COUNT: int = 1
    REDIS_URL: str = "redis://redis:6379/0"
    SYNC_HOUR_UTC: int = 2

    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8002/github/oauth/callback"
    GITHUB_OAUTH_SCOPES: str = "read:user"
    GITHUB_OAUTH_BASE: str = "https://github.com"
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_TOKEN_ENC_KEY: str = ""
    GITHUB_REPOS: str = ""

    # How far back before the cursor commits are re-requested. See sync._commit_window.
    GITHUB_SYNC_OVERLAP_MINUTES: int = Field(10080, ge=0)  # 7 days
    GITHUB_SYNC_BRANCHES: bool = True
    GITHUB_SYNC_MAX_BRANCHES: int = Field(25, ge=1)

    LLM_API_KEY: str = Field("", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_OUTPUT_TOKENS: int = 1000

    BREVO_API_KEY: str = ""
    EMAIL_FROM: str = ""
    FRONTEND_URL: str = "http://localhost:3000"

    @field_validator("DATABASE_URL")
    @classmethod
    def _pin_postgres_driver(cls, value: str) -> str:
        for scheme in DRIVERLESS_POSTGRES_SCHEMES:
            if value.startswith(scheme):
                return f"postgresql+psycopg://{value[len(scheme):]}"
        return value

    @field_validator("TRUSTED_PROXY_COUNT")
    @classmethod
    def _reject_untrustworthy_proxy_count(cls, value: int) -> int:
        if value < MIN_TRUSTED_PROXY_COUNT:
            raise ValueError(
                f"TRUSTED_PROXY_COUNT must be {MIN_TRUSTED_PROXY_COUNT} or more, got {value}. "
                "It counts hops from the RIGHT of X-Forwarded-For; 0 or negative picks an entry "
                "the caller supplied, so anyone could invent an address and get a fresh "
                "rate-limit bucket. Pulse will not run with it. Set it to the number of proxies you "
                "run in front of Pulse, e.g. TRUSTED_PROXY_COUNT=1 for a single load balancer."
            )
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def github_repos_list(self) -> list[str]:
        return [r.strip() for r in self.GITHUB_REPOS.split(",") if r.strip()]

settings = Settings()
