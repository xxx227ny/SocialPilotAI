import os
import sys
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
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
    enable_user_auth: bool = False
    allow_public_registration: bool = False
    user_auth_session_ttl_seconds: int = Field(default=604_800, ge=900, le=2_592_000)
    user_auth_cookie_secure: bool = False
    user_auth_login_max_failures: int = Field(default=5, ge=3, le=20)
    user_auth_login_window_seconds: int = Field(default=900, ge=60, le=86_400)
    user_auth_login_lock_seconds: int = Field(default=900, ge=60, le=86_400)
    account_public_web_origin: str | None = None
    account_email_from: str | None = None
    account_smtp_host: str | None = None
    account_smtp_port: int = Field(default=587, ge=1, le=65_535)
    account_smtp_username: str | None = None
    account_smtp_password: SecretStr | None = None
    account_smtp_security: str = Field(
        default="starttls", pattern=r"^(starttls|tls|none)$"
    )
    account_smtp_timeout_seconds: float = Field(default=15, gt=0, le=60)
    password_reset_token_ttl_seconds: int = Field(default=1800, ge=300, le=86_400)
    email_verification_token_ttl_seconds: int = Field(
        default=86_400, ge=900, le=604_800
    )
    account_email_request_cooldown_seconds: int = Field(
        default=60, ge=30, le=3600
    )
    user_credential_encryption_key: SecretStr | None = None
    user_credential_encryption_key_id: str = "v1"
    enable_demo_auth: bool = False
    demo_auth_username: str | None = Field(default=None, min_length=3, max_length=120)
    demo_auth_password_hash: SecretStr | None = None
    demo_auth_session_secret: SecretStr | None = None
    demo_auth_session_ttl_seconds: int = Field(default=28_800, ge=900, le=86_400)
    demo_auth_cookie_secure: bool = False
    qwen_api_key: SecretStr | None = None
    token_plan_api_key_file: str | None = None
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
    enable_qwen_video_script_generation: bool = False
    qwen_video_script_cost_min: Decimal | None = Field(default=None, ge=0)
    qwen_video_script_cost_max: Decimal | None = Field(default=None, gt=0)
    qwen_video_script_cost_currency: str = Field(
        default="CNY", pattern=r"^[A-Za-z]{3}$"
    )
    qwen_video_script_cost_basis: str | None = Field(
        default=None, min_length=1, max_length=200
    )
    qwen_video_script_preflight_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    require_live_provider_coherence: bool = False
    enable_strategy_execution: bool = False
    enable_copy_execution: bool = False
    qwen_copy_estimated_cost: Decimal = Field(default=Decimal("0.05"), gt=0)
    qwen_copy_cost_currency: str = Field(default="CNY", pattern=r"^[A-Za-z]{3}$")
    enable_v2_copy_execution: bool = False
    enable_video_project_execution: bool = False
    enable_v2_video_project_execution: bool = False
    enable_video_render_execution: bool = False
    enable_video_composition: bool = False
    enable_video_composition_enhancement: bool = False
    enable_growth_execution: bool = False
    enable_social_account_binding: bool = False
    enable_instagram_account_binding: bool = False
    enable_tiktok_account_binding: bool = False
    enable_pinterest_account_binding: bool = False
    enable_tiktok_publishing: bool = False
    enable_instagram_publishing: bool = False
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
    tiktok_client_key: str | None = None
    tiktok_client_secret: SecretStr | None = None
    tiktok_oauth_redirect_uri: str | None = None
    tiktok_request_timeout: float = Field(default=30, gt=0, le=120)
    pinterest_client_id: str | None = None
    pinterest_client_secret: SecretStr | None = None
    pinterest_oauth_redirect_uri: str | None = None
    pinterest_request_timeout: float = Field(default=30, gt=0, le=120)
    tiktok_ffprobe_path: str = "ffprobe"
    tiktok_media_probe_timeout: float = Field(default=10, gt=0, le=60)
    instagram_ffprobe_path: str = "ffprobe"
    instagram_media_probe_timeout: float = Field(default=10, gt=0, le=60)
    wanx_api_key: SecretStr | None = None
    wanx_model: str = "wan2.7-t2v"
    wanx_i2v_model: str = "wan2.6-i2v-flash"
    wanx_i2v_estimated_cost: Decimal = Field(default=Decimal("2.25"), ge=0)
    wanx_region: str = "cn-beijing"
    wanx_workspace_id: str | None = None
    wanx_endpoint: str | None = None
    wanx_timeout: float = Field(default=30, gt=0, le=300)
    wanx_image_endpoint: str = (
        "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/"
        "services/aigc/multimodal-generation/generation"
    )
    wanx_image_model: str = "wan2.7-image-pro"
    wanx_image_timeout: float = Field(default=180, gt=0, le=300)
    wanx_image_estimated_cost: Decimal = Field(default=Decimal("0.10"), ge=0)
    happyhorse_endpoint: str = "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1"
    happyhorse_model: str = "happyhorse-1.1-r2v"
    happyhorse_timeout: float = Field(default=180, gt=0, le=300)
    happyhorse_estimated_cost: Decimal = Field(default=Decimal("1.00"), ge=0)
    enable_happyhorse_product_video: bool = False
    enable_live_wanx_demo: bool = False
    video_artifact_storage_root: str | None = None
    video_composition_temp_root: str | None = None
    video_composition_ffmpeg_path: str = "ffmpeg"
    video_composition_ffprobe_path: str = "ffprobe"
    video_composition_process_timeout: float = Field(default=180, gt=0, le=900)
    execution_worker_status_file: str | None = None
    execution_worker_stale_seconds: int = Field(default=15, ge=5, le=300)
    video_artifact_max_bytes: int = Field(default=50_000_000, gt=0, le=500_000_000)
    enable_video_preview_prewarm: bool = False
    enable_real_product_video: bool = False
    product_asset_storage_root: str | None = None
    product_asset_max_bytes: int = Field(default=15_000_000, gt=0, le=50_000_000)
    qwen_tts_endpoint: str = (
        "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/"
        "services/audio/tts/SpeechSynthesizer"
    )
    qwen_tts_model: str = "qwen-audio-3.0-tts-plus"
    qwen_tts_voice: str = "longanlingxin"
    qwen_tts_timeout: float = Field(default=120, gt=0, le=300)
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

    @field_validator("qwen_video_script_cost_currency")
    @classmethod
    def normalize_qwen_cost_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_qwen_video_script_cost_policy(self) -> "Settings":
        values = (
            self.qwen_video_script_cost_min,
            self.qwen_video_script_cost_max,
            self.qwen_video_script_cost_basis,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("Qwen video script cost policy must be complete")
        if (
            self.qwen_video_script_cost_min is not None
            and self.qwen_video_script_cost_max is not None
            and self.qwen_video_script_cost_min > self.qwen_video_script_cost_max
        ):
            raise ValueError("Qwen video script cost range is invalid")
        if self.enable_demo_auth:
            if not self.demo_auth_username or not self.demo_auth_username.strip():
                raise ValueError("Demo authentication username is required")
            if self.demo_auth_password_hash is None:
                raise ValueError("Demo authentication password hash is required")
            password_hash = self.demo_auth_password_hash.get_secret_value()
            if not password_hash.startswith("pbkdf2_sha256$"):
                raise ValueError("Demo authentication password hash is invalid")
            if self.demo_auth_session_secret is None:
                raise ValueError("Demo authentication session secret is required")
            if len(self.demo_auth_session_secret.get_secret_value()) < 32:
                raise ValueError("Demo authentication session secret is too short")
        if (
            self.enable_user_auth
            and self.app_environment.casefold() == "production"
            and not self.user_auth_cookie_secure
        ):
            raise ValueError("Production user authentication requires secure cookies")
        if (
            self.enable_user_auth
            and self.app_environment.casefold() == "production"
            and self.user_credential_encryption_key is None
        ):
            raise ValueError(
                "Production user authentication requires credential encryption"
            )
        if self.enable_user_auth and self.app_environment.casefold() == "production":
            server_provider_keys = (
                self.qwen_api_key,
                self.dashscope_api_key,
                self.wanx_api_key,
            )
            has_shared_key = any(
                value is not None and bool(value.get_secret_value().strip())
                for value in server_provider_keys
            )
            has_shared_key_file = bool((self.token_plan_api_key_file or "").strip())
            if has_shared_key or has_shared_key_file:
                raise ValueError(
                    "Production user authentication forbids shared provider keys"
                )
        if bool((self.account_smtp_username or "").strip()) != (
            self.account_smtp_password is not None
            and bool(self.account_smtp_password.get_secret_value().strip())
        ):
            raise ValueError("SMTP username and password must be configured together")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=_local_env_file())


def _local_env_file() -> str | tuple[str, str] | None:
    """Load local runtime configuration, but never during tests or fake smoke."""
    disabled = os.getenv("SOCIALPILOT_DISABLE_DOTENV", "").lower()
    if disabled in {"1", "true", "yes"} or _running_under_pytest():
        return None
    profile = os.getenv("SOCIALPILOT_PROVIDER_PROFILE", "auto").strip().lower()
    if profile not in {"auto", "legacy", "token-plan"}:
        raise ValueError("SOCIALPILOT_PROVIDER_PROFILE is invalid")
    if profile == "legacy":
        return ".env"
    token_plan = Path(".env.token-plan")
    if profile == "token-plan":
        if token_plan.is_file():
            return (".env", str(token_plan))
        return str(token_plan)
    if token_plan.is_file():
        return (".env", str(token_plan))
    return ".env"


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules


settings = get_settings()
