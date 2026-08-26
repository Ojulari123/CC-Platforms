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
    # read:user identifies the person; repo is what lets Pulse read private repository
    # contents. Without repo a private sync returns nothing and looks like no activity.
    GITHUB_OAUTH_SCOPES: str = "read:user,repo"
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

    # Reports stay on OpenAI; newer AI surfaces (journal rollups, chat) prefer Anthropic
    # and fall back to the OpenAI key above when there is no Anthropic key. See
    # services/ai_provider.py. auto | anthropic | openai.
    AI_PROVIDER: str = "auto"

    ANTHROPIC_API_KEY: str = Field("", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"))
    ANTHROPIC_MODEL: str = "claude-sonnet-5"
    ANTHROPIC_TIMEOUT_SECONDS: float = 60.0

    # Caps the answer length for whichever provider ai_provider picks, not just Anthropic,
    # so it is named for the behaviour. ANTHROPIC_MAX_OUTPUT_TOKENS still populates it for
    # environments deployed before the rename.
    AI_MAX_OUTPUT_TOKENS: int = Field(1500, validation_alias=AliasChoices("AI_MAX_OUTPUT_TOKENS", "ANTHROPIC_MAX_OUTPUT_TOKENS"))

    # Embeddings are OpenAI's — Anthropic has no embeddings API — so they spend the
    # LLM_API_KEY above. EMBEDDING_DIMENSIONS only describes the model; the vector
    # column's width is fixed in the schema (models.EMBEDDING_DIM), and main.py refuses
    # to start if the two disagree.
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    INDEX_MAX_FILES: int = 3000
    INDEX_MAX_FILE_BYTES: int = 200_000
    INDEX_CHUNK_LINES: int = 60
    INDEX_CHUNK_OVERLAP: int = 10
    INDEX_EMBED_BATCH_SIZE: int = 96
    # How many blobs are fetched at once. GitHub allows 5,000 authenticated calls an hour
    # and answers a burst well; the ceiling here is politeness and the worker's memory,
    # not the quota. Set to 1 to fetch one at a time.
    INDEX_FETCH_CONCURRENCY: int = 8
    # The most files one ingest batch reads, embeds and commits. Also the resume
    # granularity: a run that dies loses at most this many files' work. A maximum rather
    # than a fixed size, because a batch priced above what the daily allowance has left is
    # halved and retried rather than refused.
    INDEX_BATCH_FILES: int = 50
    # How many retrieved chunks one chat answer is grounded in, counted across every
    # repository in scope rather than per repository.
    CHAT_TOP_K: int = 12
    # Ceiling on the citations returned with one answer. Retrieval stays wide; what comes
    # back beside the answer does not, because a citation nobody checks is worth nothing.
    CHAT_MAX_CITATIONS: int = 6
    # How long a worker may sit waiting out a model provider's per-minute limit, and how
    # many times it may try. A per-minute limit clears in seconds, so a minute of patience
    # saves a run; an outage does not clear, so holding longer than this just occupies a
    # worker. See services/provider_limits.py.
    PROVIDER_MAX_WAIT_SECONDS: int = 60
    PROVIDER_MAX_RETRIES: int = 4
    # 0 means no cap. Counted per user per UTC day across every AI surface.
    LLM_DAILY_TOKEN_CAP_PER_USER: int = 200_000

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

    @field_validator("AI_PROVIDER")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        provider = (value or "").strip().lower()
        if provider not in ("auto", "anthropic", "openai"):
            raise ValueError(f"AI_PROVIDER must be auto, anthropic or openai, got {value!r}")
        return provider

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
