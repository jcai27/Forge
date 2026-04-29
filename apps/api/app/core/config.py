from pathlib import Path

ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Verified Work-Sample Platform API"
    environment: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./verified-work-sample.db"
    frontend_url: str = "http://localhost:3000"
    public_api_origin: str = "http://127.0.0.1:8000"
    db_auto_create_schema: bool = True
    db_seed_demo_data_on_startup: bool = True

    runtime_root: str = "./.runtime"
    runtime_template_root: str = "./app/runtime/templates"
    object_store_root: str = "./.object-store"
    object_store_backend: str = "local"
    object_store_bucket: str = ""
    object_store_prefix: str = ""
    aws_region: str = "us-east-1"

    runtime_backend: str = "auto"
    runtime_docker_bin: str = "docker"
    runtime_allow_filesystem_fallback: bool | None = None
    runtime_session_cpu: str = "2"
    runtime_session_memory: str = "2g"
    runtime_session_timeout_seconds: int = 21600
    runtime_cleanup_interval_seconds: int = 300
    runtime_cleanup_on_startup: bool = True
    runtime_worker_enabled: bool = True
    runtime_worker_embed_in_api: bool | None = None
    runtime_worker_poll_interval_seconds: float = 1.0
    runtime_worker_batch_size: int = 4
    runtime_job_lease_seconds: int = 120
    runtime_job_max_attempts: int = 5

    preview_enabled: bool = True
    preview_host: str = "127.0.0.1"
    preview_port_start: int = 41000
    preview_port_end: int = 41100
    preview_idle_timeout_seconds: int = 900
    preview_startup_timeout_seconds: int = 20
    preview_cleanup_interval_seconds: int = 300

    openai_api_key: str = ""
    openai_model: str = "gpt-5.2"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: int = 90

    auth_session_cookie_name: str = "forge_session"
    auth_csrf_cookie_name: str = "forge_csrf"
    auth_session_ttl_seconds: int = 43200
    auth_magic_link_ttl_seconds: int = 1800
    auth_password_reset_ttl_seconds: int = 3600
    auth_dev_bypass_enabled: bool = True
    auth_session_secret_key: str = "dev-session-secret"
    auth_password_pepper: str = "dev-password-pepper"
    auth_signed_token_key: str = "dev-signed-token-key"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_internal_mfa_required: bool = True

    report_access_ttl_hours: int = 168
    review_sla_hours: int = 24

    model_config = SettingsConfigDict(env_file=str(ROOT_ENV_FILE), env_prefix="", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()


def validate_settings_or_raise() -> None:
    problems: list[str] = []
    if settings.object_store_backend not in {"local", "s3"}:
        problems.append("OBJECT_STORE_BACKEND must be one of: local, s3")
    if settings.auth_cookie_samesite.lower() not in {"lax", "strict", "none"}:
        problems.append("AUTH_COOKIE_SAMESITE must be one of: lax, strict, none")
    if settings.preview_port_start > settings.preview_port_end:
        problems.append("PREVIEW_PORT_START must be less than or equal to PREVIEW_PORT_END")
    if settings.runtime_job_lease_seconds <= 0:
        problems.append("RUNTIME_JOB_LEASE_SECONDS must be greater than 0")
    if settings.runtime_job_max_attempts <= 0:
        problems.append("RUNTIME_JOB_MAX_ATTEMPTS must be greater than 0")
    if settings.object_store_backend == "s3" and not settings.object_store_bucket:
        problems.append("OBJECT_STORE_BUCKET is required when OBJECT_STORE_BACKEND=s3")

    if settings.is_production:
        if settings.db_seed_demo_data_on_startup:
            problems.append("DB_SEED_DEMO_DATA_ON_STARTUP must be false in production")
        if settings.auth_dev_bypass_enabled:
            problems.append("AUTH_DEV_BYPASS_ENABLED must be false in production")
        if not settings.auth_cookie_secure:
            problems.append("AUTH_COOKIE_SECURE must be true in production")
        for field_name in ("auth_session_secret_key", "auth_password_pepper", "auth_signed_token_key"):
            field_value = getattr(settings, field_name)
            if not field_value or field_value.startswith("dev-"):
                problems.append(f"{field_name.upper()} must be set to a non-development value in production")
        if runtime_filesystem_fallback_allowed():
            problems.append("RUNTIME_ALLOW_FILESYSTEM_FALLBACK must be false in production")

    if problems:
        raise RuntimeError("Invalid application configuration: " + "; ".join(problems))


def resolve_runtime_path(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def runtime_filesystem_fallback_allowed() -> bool:
    if settings.runtime_allow_filesystem_fallback is not None:
        return settings.runtime_allow_filesystem_fallback
    return not settings.is_production


def runtime_worker_embeds_in_api() -> bool:
    if settings.runtime_worker_embed_in_api is not None:
        return settings.runtime_worker_embed_in_api
    return not settings.is_production
