"""Application configuration via Pydantic Settings — reads from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config object. All fields map directly to environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Database
    database_url: str
    database_sync_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_url: str = "http://localhost:9000"
    minio_access_key: str = "gsip"
    minio_secret_key: str = "gsip_dev_secret"
    minio_bucket: str = "gsip-layers"

    # GeoServer
    geoserver_url: str = "http://localhost:8080/geoserver"
    geoserver_user: str = "admin"
    geoserver_password: str = "gsip_geo"
    geoserver_workspace: str = "gsip"

    # OSRM
    osrm_url: str = "http://localhost:5000"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 1024
    ai_sql_timeout_s: int = 10

    # Supabase Auth
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # Feature flags
    enable_ai_query: bool = True
    enable_auth: bool = False
    enable_rate_limit: bool = False
    ai_query_rate_limit: int = 10

    @property
    def is_production(self) -> bool:
        """Return True when running in production mode."""
        return self.app_env == "production"


settings = Settings()  # type: ignore[call-arg]
