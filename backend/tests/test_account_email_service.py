from email.message import EmailMessage

import pytest

from app.core.config import Settings
from app.services import account_email_service as email_module
from app.services.account_email_service import (
    AccountEmailDeliveryError,
    SMTPAccountEmailSender,
)


def email_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "account_public_web_origin": "https://product.example",
        "account_email_from": "SocialPilot AI <account@example.com>",
        "account_smtp_host": "smtp.example.com",
        "account_smtp_port": 587,
        "account_smtp_username": "account@example.com",
        "account_smtp_password": "smtp-authorization-code",
        "account_smtp_security": "starttls",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host: str, port: int, *, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_values: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        self.__class__.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        assert context is not None
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_values = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


def test_verification_email_uses_tls_auth_and_safe_public_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    sender = SMTPAccountEmailSender(email_settings())

    sender.send_email_verification("owner@example.com", "token/with+symbols")

    connection = FakeSMTP.instances[-1]
    assert connection.host == "smtp.example.com"
    assert connection.port == 587
    assert connection.started_tls is True
    assert connection.login_values == (
        "account@example.com",
        "smtp-authorization-code",
    )
    assert connection.message is not None
    assert connection.message["To"] == "owner@example.com"
    body = connection.message.get_content()
    assert "https://product.example/?action=verify-email" in body
    assert "token%2Fwith%2Bsymbols" in body
    assert "smtp-authorization-code" not in body


def test_unconfigured_sender_fails_without_opening_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def forbidden_smtp(*_args: object, **_kwargs: object) -> None:
        nonlocal opened
        opened = True

    monkeypatch.setattr(email_module.smtplib, "SMTP", forbidden_smtp)
    sender = SMTPAccountEmailSender(
        email_settings(account_smtp_host=None, account_smtp_username=None, account_smtp_password=None)
    )

    with pytest.raises(AccountEmailDeliveryError, match="not configured"):
        sender.send_password_reset("owner@example.com", "safe-token")

    assert opened is False


def test_invalid_public_origin_is_rejected_before_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_module.smtplib,
        "SMTP",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("SMTP opened")),
    )
    sender = SMTPAccountEmailSender(
        email_settings(account_public_web_origin="https://user:pass@example.com")
    )

    with pytest.raises(AccountEmailDeliveryError, match="origin is invalid"):
        sender.send_password_reset("owner@example.com", "safe-token")
