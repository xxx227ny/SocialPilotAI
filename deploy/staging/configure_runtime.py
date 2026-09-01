"""Create the isolated staging runtime configuration without provider keys."""

import grp
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
PUBLIC_ORIGIN = "https://47.242.222.177:8443"


def load_encryption_key() -> str:
    if CONFIG_PATH.is_file():
        existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        value = str(existing.get("USER_CREDENTIAL_ENCRYPTION_KEY", "")).strip()
        if value:
            Fernet(value.encode("ascii"))
            return value
    return Fernet.generate_key().decode("ascii")


def main() -> None:
    CONFIG_PATH.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    config = {
        "APP_NAME": "socialpilot-product-staging",
        "APP_VERSION": "0.1.0-staging",
        "APP_ENVIRONMENT": "production",
        "API_V1_PREFIX": "/api/v1",
        "DEBUG": "false",
        "DATABASE_URL": "sqlite:////var/lib/socialpilot-staging/socialpilot.db",
        "CORS_ORIGINS": PUBLIC_ORIGIN,
        "ENABLE_USER_AUTH": "true",
        "ALLOW_PUBLIC_REGISTRATION": "true",
        "USER_AUTH_SESSION_TTL_SECONDS": "604800",
        "USER_AUTH_COOKIE_SECURE": "true",
        "USER_CREDENTIAL_ENCRYPTION_KEY": load_encryption_key(),
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
        "VIDEO_COMPOSITION_TEMP_ROOT": "/var/lib/socialpilot-staging/composition-temp",
        "VIDEO_ARTIFACT_MAX_BYTES": "500000000",
        "EXECUTION_WORKER_STATUS_FILE": "/var/lib/socialpilot-staging/worker-status.json",
        "SOCIALPILOT_PUBLIC_ORIGIN": PUBLIC_ORIGIN,
        "SOCIAL_FRONTEND_BASE_URL": PUBLIC_ORIGIN,
    }
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
