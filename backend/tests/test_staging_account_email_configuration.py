from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR_PATH = (
    REPOSITORY_ROOT / "deploy" / "staging" / "configure_account_email.py"
)


def _load_module():
    spec = spec_from_file_location("staging_account_email", CONFIGURATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_email_configurator_preserves_runtime_and_adds_hidden_secret() -> None:
    module = _load_module()
    existing = {
        "USER_CREDENTIAL_ENCRYPTION_KEY": "keep-me",
        "ENABLE_USER_AUTH": "true",
    }

    updated = module.build_email_update(
        existing,
        public_origin="https://staging.example.com/",
        from_address="SocialPilot AI <account@example.com>",
        smtp_host="SMTP.EXAMPLE.COM.",
        smtp_port=465,
        smtp_username="account@example.com",
        smtp_password="authorization-code",
        security="tls",
    )

    assert updated["USER_CREDENTIAL_ENCRYPTION_KEY"] == "keep-me"
    assert updated["ENABLE_USER_AUTH"] == "true"
    assert updated["ACCOUNT_PUBLIC_WEB_ORIGIN"] == "https://staging.example.com"
    assert updated["ACCOUNT_SMTP_HOST"] == "smtp.example.com"
    assert updated["ACCOUNT_SMTP_PORT"] == "465"
    assert updated["ACCOUNT_SMTP_PASSWORD"] == "authorization-code"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"public_origin": "http://example.com"}, "clean HTTPS origin"),
        ({"from_address": "bad\r\nBcc: victim@example.com"}, "From address"),
        ({"smtp_host": "https://smtp.example.com"}, "SMTP host"),
        ({"smtp_port": 70_000}, "SMTP port"),
        ({"smtp_password": None}, "required together"),
    ],
)
def test_email_configurator_rejects_unsafe_or_incomplete_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    module = _load_module()
    values: dict[str, object] = {
        "public_origin": "https://staging.example.com",
        "from_address": "account@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "account@example.com",
        "smtp_password": "authorization-code",
        "security": "starttls",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        module.build_email_update({}, **values)
