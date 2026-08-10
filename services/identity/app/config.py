from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Counts hops from the RIGHT of X-Forwarded-For, so anything below 1 reads a
# caller-supplied entry — the exact thing the setting exists to avoid.
MIN_TRUSTED_PROXY_COUNT = 1

class Settings(BaseSettings):
    # validate_assignment so the guards below can't be undone by writing to settings later.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", validate_assignment=True)

    DATABASE_URL: str
    JWT_PRIVATE_KEY_PATH: str = "./keys/private.pem"
    JWT_PUBLIC_KEY_PATH: str = "./keys/public.pem"
    # Public keys of superseded signing keys. Still verified, never signed with.
    JWT_RETIRED_PUBLIC_KEYS_DIR: str = "./keys/retired"
    JWT_ALGORITHM: str = "RS256"
    JWT_ISSUER: str = "cyphercrescent-identity"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    SERVICE_TOKEN_EXPIRE_MINUTES: int = 10
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Both product frontends in dev: Forge on 3000, Pulse on 3001. They have to be
    # different ports so both can run at once — identity is shared by both.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    RATE_LIMIT_ENABLED: bool = True
    # Only turn on when identity really is behind proxies we control — see .env.example.
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_COUNT: int = 1
    BREVO_API_KEY: str = ""
    EMAIL_FROM: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    INVITE_EXPIRE_DAYS: int = 7
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    SIGNUP_ALLOWED_DOMAINS: str = ""
    PULSE_CLIENT_ID: str = "pulse"
    PULSE_CLIENT_SECRET: str = ""
    FORGE_CLIENT_ID: str = "forge"
    FORGE_CLIENT_SECRET: str = ""

    @field_validator("TRUSTED_PROXY_COUNT")
    @classmethod
    def _reject_untrustworthy_proxy_count(cls, value: int) -> int:
        if value < MIN_TRUSTED_PROXY_COUNT:
            raise ValueError(
                f"TRUSTED_PROXY_COUNT must be {MIN_TRUSTED_PROXY_COUNT} or more, got {value}. "
                "It counts hops from the RIGHT of X-Forwarded-For; 0 or negative picks an entry "
                "the caller supplied, so anyone could invent an address and get a fresh "
                "rate-limit bucket. Identity will not run with it. Set it to the number of proxies you "
                "run in front of identity, e.g. TRUSTED_PROXY_COUNT=1 for a single load balancer."
            )
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def signup_allowed_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.SIGNUP_ALLOWED_DOMAINS.split(",") if d.strip()]

settings = Settings()
