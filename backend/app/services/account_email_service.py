from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Annotated, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import Depends

from app.core.config import Settings, get_settings


class AccountEmailDeliveryError(RuntimeError):
    """Raised when an account email cannot be delivered safely."""


class AccountEmailSender(Protocol):
    @property
    def configured(self) -> bool: ...

    def send_password_reset(self, recipient: str, token: str) -> None: ...

    def send_email_verification(self, recipient: str, token: str) -> None: ...


class SMTPAccountEmailSender:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def configured(self) -> bool:
        return all(
            (
                (self._settings.account_public_web_origin or "").strip(),
                (self._settings.account_email_from or "").strip(),
                (self._settings.account_smtp_host or "").strip(),
            )
        )

    def send_password_reset(self, recipient: str, token: str) -> None:
        url = self._action_url("reset-password", token)
        self._send(
            recipient,
            subject="重置你的 SocialPilot AI 密码",
            body=(
                "你申请了重置 SocialPilot AI 密码。\n\n"
                f"请在有效期内打开此链接：\n{url}\n\n"
                "如果不是你本人操作，请忽略此邮件。"
            ),
        )

    def send_email_verification(self, recipient: str, token: str) -> None:
        url = self._action_url("verify-email", token)
        self._send(
            recipient,
            subject="验证你的 SocialPilot AI 邮箱",
            body=(
                "请验证你用于 SocialPilot AI 的邮箱。\n\n"
                f"请在有效期内打开此链接：\n{url}\n\n"
                "如果不是你本人操作，请忽略此邮件。"
            ),
        )

    def _action_url(self, action: str, token: str) -> str:
        raw_origin = (self._settings.account_public_web_origin or "").strip()
        parsed = urlsplit(raw_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AccountEmailDeliveryError("Account web origin is invalid")
        path = parsed.path.rstrip("/") or "/"
        origin = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        separator = "&" if "?" in origin else "?"
        return f"{origin}{separator}action={action}&token={quote(token, safe='')}"

    def _send(self, recipient: str, *, subject: str, body: str) -> None:
        if not self.configured:
            raise AccountEmailDeliveryError("Account email delivery is not configured")
        message = EmailMessage()
        message["From"] = (self._settings.account_email_from or "").strip()
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        host = (self._settings.account_smtp_host or "").strip()
        password = (
            self._settings.account_smtp_password.get_secret_value()
            if self._settings.account_smtp_password is not None
            else None
        )
        try:
            if self._settings.account_smtp_security == "tls":
                connection = smtplib.SMTP_SSL(
                    host,
                    self._settings.account_smtp_port,
                    timeout=self._settings.account_smtp_timeout_seconds,
                    context=ssl.create_default_context(),
                )
            else:
                connection = smtplib.SMTP(
                    host,
                    self._settings.account_smtp_port,
                    timeout=self._settings.account_smtp_timeout_seconds,
                )
            with connection:
                if self._settings.account_smtp_security == "starttls":
                    connection.starttls(context=ssl.create_default_context())
                if self._settings.account_smtp_username and password:
                    connection.login(self._settings.account_smtp_username, password)
                connection.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise AccountEmailDeliveryError("Account email delivery failed") from exc


def get_account_email_sender(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccountEmailSender:
    return SMTPAccountEmailSender(settings)


AccountEmailSenderDep = Annotated[AccountEmailSender, Depends(get_account_email_sender)]
