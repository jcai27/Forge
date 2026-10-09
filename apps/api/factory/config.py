from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./factory.db"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    execution_mode: str = "demo"
    estimated_token_cost: float = 0.000005
    worker_lease_seconds: int = 360
    runtime_max_attempts: int = 3
    jwt_secret: str = "local-development-only-change-before-deployment"
    encryption_key: str = ""
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    def validate_production(self):
        if self.environment == "production":
            if len(self.jwt_secret) < 40 or self.jwt_secret.startswith("local-"):
                raise ValueError("Production requires a strong JWT_SECRET")
            if not self.encryption_key:
                raise ValueError("Production requires ENCRYPTION_KEY")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")


@lru_cache
def settings():
    value = Settings()
    value.validate_production()
    return value
