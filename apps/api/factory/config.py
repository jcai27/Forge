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
    # "demo", "live", or "hybrid": built-in templates on fixtures, custom agents on the real model.
    execution_mode: str = "demo"
    # Flat fallback, per token, for a model with no entry in model_prices.
    estimated_token_cost: float = 0.000005
    # Dollars per million tokens as [input, output]; output includes reasoning. Defaults are published
    # list prices as last checked and may be out of date: override with MODEL_PRICES as JSON.
    # A third number is the price of input served from the provider's prompt cache.
    model_prices: dict[str, list[float]] = {
        "gpt-6-astra": [10.0, 50.0, 1.0],
        "gpt-6-sol": [2.0, 10.0, 0.2],
        "gpt-6-luna": [0.1, 0.5, 0.01],
        "gpt-5.5": [5.0, 30.0, 0.5],
        "gpt-4.1-mini": [0.4, 1.6, 0.1],
    }
    # Models the builder may move an agent to. Empty: the agent stays on the model it was created with.
    agent_models: list[str] = []
    # Reasoning effort requested from reasoning models ("low", "medium", "high"). Empty leaves the default.
    agent_reasoning_effort: str = ""
    builder_reasoning_effort: str = ""
    # Live evaluation trials run side by side. One restores the strictly sequential loop.
    evaluation_concurrency: int = 8
    # Largest reply to request from a model. Zero leaves it to the model's own maximum: a fixed cap
    # cuts a reasoning model off mid-answer, and time limits and budgets already bound a call.
    output_token_limit: int = 0
    # Reading scanned pages and photos sends each page image to the model provider and is charged per
    # page. Off unless explicitly enabled. reader_model falls back to openai_model.
    document_reading: bool = False
    reader_model: str = ""
    reader_reasoning_effort: str = "low"
    reading_concurrency: int = 4
    # Ceiling on what one upload may spend on reading, in dollars. Pages already read are kept.
    reading_max_cost: float = 10
    reading_timeout_seconds: int = 180
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
        if self.execution_mode not in ("demo", "live", "hybrid"):
            raise ValueError("EXECUTION_MODE must be demo, live or hybrid")

    def validate_production(self):
        if self.environment == "production":
            if len(self.jwt_secret) < 40 or self.jwt_secret.startswith("local-"):
                raise ValueError("Production requires a strong JWT_SECRET")
            if not self.encryption_key:
                raise ValueError("Production requires ENCRYPTION_KEY")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")


def mode_for(template):
    """Whether an agent of this kind runs on fixtures ("demo") or on a real model ("live").

    In hybrid mode the built-in templates keep replaying their fixtures, free and deterministic, while
    custom agents use the real model. Every run records the mode it actually used.
    """
    mode = settings().execution_mode
    return ("live" if template == "custom" else "demo") if mode == "hybrid" else mode


@lru_cache
def settings():
    value = Settings()
    value.validate_provider()
    value.validate_production()
    return value
