"""Create the isolated staging runtime configuration without provider keys."""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

CONFIG_PATH = Path(
    os.environ.get(
        "SOCIALPILOT_SERVER_CONFIG",
        "/etc/socialpilot-staging/runtime.json",
    )
)
PUBLIC_ORIGIN = "https://staging.47.242.222.177.nip.io"
PRESERVED_ACCOUNT_EMAIL_KEYS = (
    "ACCOUNT_EMAIL_FROM",
    "ACCOUNT_SMTP_HOST",
    "ACCOUNT_SMTP_PORT",
    "ACCOUNT_SMTP_USERNAME",
    "ACCOUNT_SMTP_PASSWORD",
    "ACCOUNT_SMTP_SECURITY",
    "ACCOUNT_SMTP_TIMEOUT_SECONDS",
)


def load_existing_config() -> dict[str, object]:
    if not CONFIG_PATH.is_file():
        return {}
    loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Existing runtime configuration must be a JSON object")
    return loaded


def load_encryption_key(existing: dict[str, object]) -> str:
    value = str(existing.get("USER_CREDENTIAL_ENCRYPTION_KEY", "")).strip()
    if value:
        Fernet(value.encode("ascii"))
        return value
    return Fernet.generate_key().decode("ascii")


def build_runtime_config(existing: dict[str, object]) -> dict[str, object]:
    config = {
        "APP_NAME": "socialpilot-product-staging",
        "APP_VERSION": "0.1.0-staging",
        "APP_ENVIRONMENT": "production",
        "API_V1_PREFIX": "/api/v1",
        "DEBUG": "false",
        "DATABASE_URL": "sqlite:////var/lib/socialpilot-staging/socialpilot.db",
        "CORS_ORIGINS": json.dumps([PUBLIC_ORIGIN]),
        "ENABLE_USER_AUTH": "true",
        "ALLOW_PUBLIC_REGISTRATION": "true",
        "USER_AUTH_SESSION_TTL_SECONDS": "604800",
        "USER_AUTH_COOKIE_SECURE": "true",
        "USER_CREDENTIAL_ENCRYPTION_KEY": load_encryption_key(existing),
        "USER_CREDENTIAL_ENCRYPTION_KEY_ID": "v1",
        "ENABLE_DEMO_AUTH": "false",
        "REQUIRE_LIVE_PROVIDER_COHERENCE": "false",
        "ENABLE_STRATEGY_EXECUTION": "true",
        "ENABLE_COPY_EXECUTION": "true",
        "ENABLE_V2_COPY_EXECUTION": "true",
        "ENABLE_VIDEO_PROJECT_EXECUTION": "true",
        "ENABLE_V2_VIDEO_PROJECT_EXECUTION": "true",
        "ENABLE_VIDEO_RENDER_EXECUTION": "true",
        "ENABLE_VIDEO_COMPOSITION": "true",
        "ENABLE_VIDEO_COMPOSITION_ENHANCEMENT": "true",
        "ENABLE_QWEN_VIDEO_SCRIPT_GENERATION": "true",
        "ENABLE_REAL_PRODUCT_VIDEO": "true",
        "ENABLE_HAPPYHORSE_PRODUCT_VIDEO": "true",
        "ENABLE_GROWTH_EXECUTION": "true",
        "ENABLE_LIVE_WANX_DEMO": "false",
        "ENABLE_SOCIAL_ACCOUNT_BINDING": "false",
        "ENABLE_INSTAGRAM_ACCOUNT_BINDING": "false",
        "ENABLE_TIKTOK_ACCOUNT_BINDING": "false",
        "ENABLE_PINTEREST_ACCOUNT_BINDING": "false",
        "ENABLE_YOUTUBE_PUBLISHING": "false",
        "ENABLE_INSTAGRAM_PUBLISHING": "false",
        "ENABLE_TIKTOK_PUBLISHING": "false",
        "VIDEO_ARTIFACT_STORAGE_ROOT": "/var/lib/socialpilot-staging/artifacts",
        "PRODUCT_ASSET_STORAGE_ROOT": "/var/lib/socialpilot-staging/product-assets",
        "PRODUCT_ASSET_WORKSPACE_MAX_BYTES": "250000000",
        "VIDEO_COMPOSITION_TEMP_ROOT": "/var/lib/socialpilot-staging/composition-temp",
        "VIDEO_ARTIFACT_MAX_BYTES": "500000000",
        "ENABLE_VIDEO_PREVIEW_PREWARM": "true",
        "EXECUTION_WORKER_STATUS_FILE": "/var/lib/socialpilot-staging/worker-status.json",
        "SOCIALPILOT_PUBLIC_ORIGIN": PUBLIC_ORIGIN,
        "SOCIAL_FRONTEND_BASE_URL": PUBLIC_ORIGIN,
        "ACCOUNT_PUBLIC_WEB_ORIGIN": PUBLIC_ORIGIN,
    }
    # Email delivery belongs to the server, while Qwen/Wanx credentials belong
    # to each user workspace. Preserve only the explicit SMTP allowlist when a
    # runtime file is regenerated; never copy shared Provider credentials.
    for key in PRESERVED_ACCOUNT_EMAIL_KEYS:
        value = existing.get(key)
        if value is not None and str(value).strip():
            config[key] = value
    return config


def main() -> None:
    import grp

    CONFIG_PATH.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    config = build_runtime_config(load_existing_config())
    temporary = CONFIG_PATH.with_suffix(".json.new")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    socialpilot_gid = grp.getgrnam("socialpilot").gr_gid
    os.chown(temporary, 0, socialpilot_gid)
    temporary.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH.parent, 0o750)
    os.chown(CONFIG_PATH.parent, 0, socialpilot_gid)
    print(f"Created secure staging runtime configuration at {CONFIG_PATH}")


if __name__ == "__main__":
    main()
