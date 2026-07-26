from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "socialpilot-api"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    database_url: str = "sqlite:///./socialpilot.db"
    dashscope_api_key: SecretStr | None = None
    qwen_model: str = "qwen-plus"
    qwen_timeout: float = Field(default=30, gt=0, le=300)
    enable_strategy_execution: bool = False
    enable_copy_execution: bool = False
    wanx_api_key: SecretStr | None = None
    wanx_model: str = "wan2.7-t2v"
    wanx_region: str = "cn-beijing"
    wanx_workspace_id: str | None = None
    wanx_endpoint: str | None = None
    wanx_timeout: float = Field(default=30, gt=0, le=300)
    enable_live_wanx_demo: bool = False
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
    return Settings()


settings = get_settings()
