from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from cryptography.fernet import Fernet

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIGURE_RUNTIME_PATH = REPOSITORY_ROOT / "deploy" / "staging" / "configure_runtime.py"


def _load_module():
    spec = spec_from_file_location("staging_configure_runtime", CONFIGURE_RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_regeneration_preserves_only_server_email_credentials() -> None:
    module = _load_module()
    encryption_key = Fernet.generate_key().decode("ascii")
    existing = {
        "USER_CREDENTIAL_ENCRYPTION_KEY": encryption_key,
        "ACCOUNT_EMAIL_FROM": "SocialPilot AI <account@example.com>",
        "ACCOUNT_SMTP_HOST": "smtp.example.com",
        "ACCOUNT_SMTP_PORT": "465",
        "ACCOUNT_SMTP_USERNAME": "account@example.com",
        "ACCOUNT_SMTP_PASSWORD": "smtp-authorization-code",
        "ACCOUNT_SMTP_SECURITY": "tls",
        "ACCOUNT_SMTP_TIMEOUT_SECONDS": "12",
        "ACCOUNT_REQUIRE_VERIFIED_EMAIL": "true",
        "QWEN_API_KEY": "must-not-be-preserved",
        "DASHSCOPE_API_KEY": "must-not-be-preserved",
        "WANX_API_KEY": "must-not-be-preserved",
    }

    config = module.build_runtime_config(existing)

    assert config["USER_CREDENTIAL_ENCRYPTION_KEY"] == encryption_key
    assert config["ACCOUNT_PUBLIC_WEB_ORIGIN"] == module.PUBLIC_ORIGIN
    for key in module.PRESERVED_ACCOUNT_EMAIL_KEYS:
        assert config[key] == existing[key]
    assert "QWEN_API_KEY" not in config
    assert "DASHSCOPE_API_KEY" not in config
    assert "WANX_API_KEY" not in config
    assert config["QWEN_VIDEO_SCRIPT_COST_MIN"] == "0.01"
    assert config["QWEN_VIDEO_SCRIPT_COST_MAX"] == "0.05"
    assert config["QWEN_VIDEO_SCRIPT_COST_CURRENCY"] == "CNY"
    assert "qwen-plus cn-beijing" in str(config["QWEN_VIDEO_SCRIPT_COST_BASIS"])


def test_new_runtime_generates_valid_encryption_key_and_no_shared_keys() -> None:
    module = _load_module()

    config = module.build_runtime_config({})

    Fernet(str(config["USER_CREDENTIAL_ENCRYPTION_KEY"]).encode("ascii"))
    assert config["ACCOUNT_PUBLIC_WEB_ORIGIN"] == module.PUBLIC_ORIGIN
    shared_keys = ("QWEN_API_KEY", "DASHSCOPE_API_KEY", "WANX_API_KEY")
    assert not any(key in config for key in shared_keys)
    assert config["QWEN_VIDEO_SCRIPT_COST_MIN"] == "0.01"
    assert config["QWEN_VIDEO_SCRIPT_COST_MAX"] == "0.05"
