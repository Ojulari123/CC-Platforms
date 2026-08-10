from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Counts hops from the RIGHT of X-Forwarded-For, so anything below 1 reads a
# caller-supplied entry — the exact thing the setting exists to avoid.
MIN_TRUSTED_PROXY_COUNT = 1

class Settings(BaseSettings):
    # validate_assignment so the guards below can't be undone by writing to settings later.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)

    DATABASE_URL: str
    IDENTITY_JWKS_URL: str = "http://identity:8000/.well-known/jwks.json"

    # Service-to-service auth against identity. IDENTITY_API_URL is identity's internal
    # base (mirrors the host in IDENTITY_JWKS_URL). The client secret is blank by default
    # so imports/CI never need it; when it's blank the identity client refuses to call and
    # callers log-and-skip. A real deploy sets the secret issued to the "pulse" client.
    IDENTITY_API_URL: str = "http://identity:8000"
    PULSE_SERVICE_CLIENT_ID: str = "pulse"
    PULSE_SERVICE_CLIENT_SECRET: str = ""

    JWT_ISSUER: str = "cyphercrescent-identity"
    JWKS_TTL_SECONDS: int = 3600
    # How long a user's token_version is cached before identity is asked again — the
    # worst-case delay between "log out everywhere" and Pulse rejecting the token.
    TOKEN_VERSION_TTL_SECONDS: int = 60
    # Pulse's own frontend runs on 3001 in dev (Forge holds 3000). 3000 stays allowed
    # so a browser tab left on the other product's port isn't a silent CORS failure.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    RATE_LIMIT_ENABLED: bool = True
    # Only turn on when Pulse really is behind proxies we control — see .env.example.
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

    # LLM (report generation). Key is blank by default so imports/CI never need it;
    # a real deploy sets it. Accept OPENAI_API_KEY too, since that's what the OpenAI
    # tooling names the key — either env var populates this one setting.
    LLM_API_KEY: str = Field("", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_OUTPUT_TOKENS: int = 1000

    # Outbound email (Brevo). Blank by default so imports/CI never need it; a real
    # deploy sets these. FRONTEND_URL builds the report link in notification emails, and
    # is where the GitHub OAuth callback hands the browser back to.
    BREVO_API_KEY: str = ""
    EMAIL_FROM: str = ""
    FRONTEND_URL: str = "http://localhost:3000"

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
