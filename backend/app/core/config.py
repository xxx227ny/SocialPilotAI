import os
import sys
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "socialpilot-api"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    database_url: str = "sqlite:///./socialpilot.db"
    qwen_api_key: SecretStr | None = None
    # Deprecated one-way alias for QWEN_API_KEY. Never used by Wanx.
    dashscope_api_key: SecretStr | None = None
    qwen_workspace_id: str | None = None
    qwen_region: str = "cn-beijing"
    qwen_model: str = "qwen-plus"
    qwen_endpoint: str | None = None
    qwen_timeout: float = Field(default=120, gt=0, le=120)
    qwen_connect_timeout: float = Field(default=10, gt=0, le=30)
    qwen_read_timeout: float = Field(default=120, gt=0, le=120)
    qwen_write_timeout: float = Field(default=30, gt=0, le=60)
    qwen_pool_timeout: float = Field(default=10, gt=0, le=30)
    require_live_provider_coherence: bool = False
    enable_strategy_execution: bool = False
    enable_copy_execution: bool = False
    enable_v2_copy_execution: bool = False
    enable_video_project_execution: bool = False
    enable_v2_video_project_execution: bool = False
    enable_video_render_execution: bool = False
    enable_growth_execution: bool = False
    enable_social_account_binding: bool = False
    enable_instagram_account_binding: bool = False
    enable_youtube_publishing: bool = False
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = (
        "http://127.0.0.1:8000/api/v1/social-accounts/youtube/callback"
    )
    social_token_encryption_key: SecretStr | None = None
    social_token_encryption_key_id: str = "v1"
    frontend_social_redirect_path: str = "/products"
    social_frontend_base_url: str = "http://127.0.0.1:5173"
    youtube_request_timeout: float = Field(default=30, gt=0, le=120)
    instagram_app_id: str | None = None
    instagram_app_secret: SecretStr | None = None
    instagram_oauth_redirect_uri: str | None = None
    instagram_graph_api_version: str | None = Field(
        default=None, pattern=r"^v[0-9]+\.[0-9]+$"
    )
    instagram_request_timeout: float = Field(default=30, gt=0, le=120)
    wanx_api_key: SecretStr | None = None
    wanx_model: str = "wan2.7-t2v"
    wanx_region: str = "cn-beijing"
    wanx_workspace_id: str | None = None
    wanx_endpoint: str | None = None
    wanx_timeout: float = Field(default=30, gt=0, le=300)
    enable_live_wanx_demo: bool = False
    video_artifact_storage_root: str | None = None
    execution_worker_status_file: str | None = None
    execution_worker_stale_seconds: int = Field(default=15, ge=5, le=300)
    video_artifact_max_bytes: int = Field(
        default=50_000_000, gt=0, le=500_000_000
    )
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=_local_env_file())


def _local_env_file() -> str | None:
    """Load local runtime configuration, but never during tests or fake smoke."""
    disabled = os.getenv("SOCIALPILOT_DISABLE_DOTENV", "").lower()
    if disabled in {"1", "true", "yes"} or "pytest" in sys.modules:
        return None
    return ".env"


settings = get_settings()
