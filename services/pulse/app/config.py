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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

settings = Settings()
