from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    IDENTITY_JWKS_URL: str = "http://identity:8000/.well-known/jwks.json"

    JWT_ISSUER: str = "cyphercrescent-identity"
    JWKS_TTL_SECONDS: int = 3600
    CORS_ORIGINS: str = "http://localhost:3000"

    RATE_LIMIT_ENABLED: bool = True
    REDIS_URL: str = "redis://redis:6379/0"
    SYNC_HOUR_UTC: int = 2

    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8002/github/oauth/callback"
    GITHUB_OAUTH_SCOPES: str = "read:user"
    GITHUB_OAUTH_BASE: str = "https://github.com"
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_TOKEN_ENC_KEY: str = ""
    GITHUB_ORG: str = ""
    GITHUB_REPOS: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def github_repos_list(self) -> list[str]:
        return [r.strip() for r in self.GITHUB_REPOS.split(",") if r.strip()]

settings = Settings()
