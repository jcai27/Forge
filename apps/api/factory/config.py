from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./factory.db"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    # Optional OpenAI-compatible endpoint (for example a local model server). Empty uses the OpenAI API.
    openai_base_url: str = ""
    # "responses" (OpenAI) or "chat_completions" (most compatible servers).
    openai_api: str = "responses"
    # "schema" sends the output JSON Schema to the provider. "prompt" puts it in the instructions and
    # validates the reply in code, for servers that cannot compile large schemas.
    openai_structured_output: str = "schema"
    # Model used by factory roles (architect, optimizer, test designer). Falls back to openai_model.
    builder_model: str = ""
    # Open-web research for the builder. Off unless explicitly enabled for a deployment.
    research_enabled: bool = False
    # Optional JSON search endpoint containing "{query}", and an optional "Name: value" header.
    research_search_url: str = ""
    research_search_header: str = ""
    # Unix socket of the sandbox service that runs builder-written tools. Empty disables them.
    sandbox_socket: str = ""
    execution_mode: str = "demo"
    estimated_token_cost: float = 0.000005
    worker_lease_seconds: int = 360
    runtime_max_attempts: int = 3
    jwt_secret: str = "local-development-only-change-before-deployment"
    encryption_key: str = ""
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    def validate_provider(self):
        if self.openai_api not in ("responses", "chat_completions"):
            raise ValueError("OPENAI_API must be responses or chat_completions")
        if self.openai_structured_output not in ("schema", "prompt"):
            raise ValueError("OPENAI_STRUCTURED_OUTPUT must be schema or prompt")

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
    value.validate_provider()
    value.validate_production()
    return value
