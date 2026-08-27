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

    # Image datasets. The archive is bigger than a CSV but the pieces inside it are small,
    # so the limits are separate: one on the upload, one on what it unpacks to, one per
    # image, and one on how many images a single run will read.
    MAX_IMAGE_UPLOAD_MB: int = 25
    MAX_IMAGE_TOTAL_MB: int = 100
    MAX_IMAGE_FILE_MB: int = 5
    MAX_IMAGE_COUNT: int = 2_000
    # Below this a class score is measuring the split, not the model.
    MIN_IMAGES_PER_CLASS: int = 5
    # Longest edge an image is shrunk to before it is sent to the vision model. Measured
    # against gpt-4o-mini on the same picture: 768 px billed 25,573 tokens, 512 px billed
    # 8,588, and the two descriptions said the same things. Three times the spend for no
    # extra detail is not a trade worth taking by default.
    CAPTION_MAX_EDGE: int = 512
    # What one image is assumed to cost when the budget is checked up front. The provider
    # bills an image by how many tiles it covers, none of which shows up in the text, and
    # an estimate that comes in low turns a cap into a report of overspending. Set above
    # the 8,588 measured above so it stays a bound rather than a guess.
    CAPTION_IMAGE_TOKEN_ESTIMATE: int = 10_000

    # Training runs on the same small box as everything else, so a run is refused before
    # it starts rather than after it has taken the worker down. Cells, not just rows: a
    # 2,000-row file with 900 one-hot columns costs the same as a huge one.
    MAX_TRAIN_ROWS: int = 200_000
    MAX_TRAIN_CELLS: int = 5_000_000
    MIN_TRAIN_ROWS: int = 10

    # LLM playground. Blank key means the playground answers "not set up" and nothing else
    # in Forge changes, so CI and imports never need a key.
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: int = 60
    # Daily ceiling per user across every playground call. 0 turns the cap off.
    LLM_DAILY_TOKEN_CAP: int = 100_000

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
