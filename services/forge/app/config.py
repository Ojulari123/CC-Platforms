from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Counts hops from the RIGHT of X-Forwarded-For, so anything below 1 reads a
# caller-supplied entry, the exact thing the setting exists to avoid.
MIN_TRUSTED_PROXY_COUNT = 1

# Managed Postgres providers (Render's fromDatabase wiring, Heroku, Neon's copy
# button) hand out URLs on these schemes. SQLAlchemy reads a bare postgresql://
# as "use psycopg2", which is not in requirements.txt, so the app would fail to
# boot on a URL nobody typed wrong. Rewritten to the psycopg 3 driver we ship.
DRIVERLESS_POSTGRES_SCHEMES = ("postgresql://", "postgres://")

class Settings(BaseSettings):
    # validate_assignment so the guards below can't be undone by writing to settings later.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)

    DATABASE_URL: str
    IDENTITY_JWKS_URL: str = "http://identity:8000/.well-known/jwks.json"

    # Service-to-service auth against identity. IDENTITY_API_URL is identity's internal
    # base (mirrors the host in IDENTITY_JWKS_URL). The client secret is blank by default
    # so imports/CI never need it; blank means Forge cannot authenticate to identity at all.
    IDENTITY_API_URL: str = "http://identity:8000"
    FORGE_SERVICE_CLIENT_ID: str = "forge"
    FORGE_SERVICE_CLIENT_SECRET: str = ""

    # How long a user's token_version is trusted before Forge re-asks identity. This is
    # the worst-case survival time of a revoked session; 60s is the agreed trade.
    TOKEN_VERSION_TTL_SECONDS: int = 60

    JWT_ISSUER: str = "cyphercrescent-identity"
    JWKS_TTL_SECONDS: int = 3600
    # Forge's own frontend 3000, plus identity's admin UI 3002 — identity's product picker
    # reads live counts straight from Forge, so its origin has to be on the list.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3002"

    RATE_LIMIT_ENABLED: bool = True
    REDIS_URL: str = "redis://redis:6379/0"
    # Only turn on when Forge really is behind proxies we control. See .env.example.
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_COUNT: int = 1

    DATASET_PREVIEW_ROWS: int = 10
    MAX_UPLOAD_MB: int = 5

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
                "rate-limit bucket. Forge will not run with it. Set it to the number of proxies you "
                "run in front of Forge, e.g. TRUSTED_PROXY_COUNT=1 for a single load balancer."
            )
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

settings = Settings()
