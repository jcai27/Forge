from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Verified Work-Sample Platform API"
    environment: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./verified-work-sample.db"
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()

