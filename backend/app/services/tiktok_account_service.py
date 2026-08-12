from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import OAuthSession, Product, SocialAccount
from app.providers.tiktok_provider import (
    TIKTOK_SCOPES,
    TikTokProvider,
    TikTokProviderError,
)
from app.repositories.social import SocialRepository
from app.schemas.social import (
    SocialAccountRead,
    TikTokConnectRead,
    TikTokDisconnectRead,
)
from app.services.social_security import (
    TokenCipher,
    digest_oauth_state,
    generate_oauth_state,
)

TIKTOK_OAUTH_SESSION_LIFETIME = timedelta(minutes=10)


class TikTokAccountService:
    def __init__(
        self, session: Session, settings: Settings, provider: TikTokProvider | None
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.repository = SocialRepository(session)

    def connect(
        self, product_id: int, *, browser_session_digest: str
    ) -> TikTokConnectRead:
        self._require_enabled()
        if self.session.get(Product, product_id) is None:
            raise AppError("Product not found", 404)
        cipher = TokenCipher(self.settings)
        state = generate_oauth_state()
        expires_at = datetime.now(UTC) + TIKTOK_OAUTH_SESSION_LIFETIME
        self.session.add(
            OAuthSession(
                product_id=product_id,
                platform="tiktok",
                state_digest=digest_oauth_state(state),
                browser_session_digest=browser_session_digest,
                # Shared legacy column stores only an encrypted internal flow nonce.
                pkce_verifier_ciphertext=cipher.encrypt(secrets.token_urlsafe(48)),
                redirect_path=self._safe_redirect_path(),
                expires_at=expires_at,
            )
        )
        self.session.commit()
        return TikTokConnectRead(
            authorization_url=self._provider().authorization_url(state=state),
            expires_at=expires_at,
        )

    async def callback(
        self,
        *,
        state: str,
        browser_session_digest: str,
        code: str | None,
        error: str | None,
    ) -> str:
        self._require_enabled()
        oauth = self.repository.get_oauth_session(digest_oauth_state(state))
        if oauth is None or oauth.platform != "tiktok":
            raise AppError("TikTok OAuth state is invalid", 400)
        if not hmac.compare_digest(
            oauth.browser_session_digest, browser_session_digest
        ):
            raise AppError("TikTok OAuth browser session does not match", 400)
        if oauth.consumed_at is not None:
            raise AppError("TikTok OAuth state has already been used", 409)
        if _as_utc(oauth.expires_at) <= datetime.now(UTC):
            raise AppError("TikTok OAuth state has expired", 410)
        oauth.consumed_at = datetime.now(UTC)
        self.session.commit()
        if error is not None:
            return self._frontend_redirect(oauth.redirect_path, "denied")
        if not code:
            return self._frontend_redirect(oauth.redirect_path, "failed")

        cipher = TokenCipher(self.settings)
        try:
            cipher.decrypt(oauth.pkce_verifier_ciphertext)
            token = await self._provider().exchange_code(code=code)
            if set(token.scopes) != set(TIKTOK_SCOPES) or len(token.scopes) != len(
                TIKTOK_SCOPES
            ):
                raise TikTokProviderError("tiktok_scope_mismatch")
            user = await self._provider().get_user(access_token=token.access_token)
            if user.open_id != token.open_id:
                raise TikTokProviderError("tiktok_open_id_mismatch")
        except (TikTokProviderError, AppError):
            return self._frontend_redirect(oauth.redirect_path, "failed")

        account = self.repository.get_account_by_provider_identity(
            oauth.product_id, "tiktok", token.open_id
        )
        values = {
            "display_name": user.display_name,
            "scopes": list(TIKTOK_SCOPES),
            "access_token_ciphertext": cipher.encrypt(token.access_token),
            "refresh_token_ciphertext": cipher.encrypt(token.refresh_token),
            "token_expires_at": token.access_token_expires_at,
            "refresh_token_expires_at": token.refresh_token_expires_at,
            "connection_status": "CONNECTED",
            "encryption_key_id": cipher.key_id,
            "disconnected_at": None,
        }
        if account is None:
            account = SocialAccount(
                product_id=oauth.product_id,
                platform="tiktok",
                provider_account_id=token.open_id,
                **values,
            )
            self.session.add(account)
        else:
            for name, value in values.items():
                setattr(account, name, value)
        self.session.commit()
        return self._frontend_redirect(oauth.redirect_path, "connected")

    def disconnect(self, account_id: int, *, product_id: int) -> TikTokDisconnectRead:
        self._require_enabled()
        account = self.repository.get_account(account_id)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "tiktok"
        ):
            raise AppError("TikTok account not found", 404)
        account.access_token_ciphertext = None
        account.refresh_token_ciphertext = None
        account.token_expires_at = None
        account.refresh_token_expires_at = None
        account.connection_status = "DISCONNECTED"
        account.disconnected_at = datetime.now(UTC)
        self.session.commit()
        return TikTokDisconnectRead(account=SocialAccountRead.model_validate(account))

    def _require_enabled(self) -> None:
        if not self.settings.enable_tiktok_account_binding:
            raise AppError("TikTok account binding is disabled by the server", 503)

    def _provider(self) -> TikTokProvider:
        if self.provider is None:
            raise AppError("TikTok OAuth provider is unavailable", 503)
        return self.provider

    def _safe_redirect_path(self) -> str:
        if self.settings.frontend_social_redirect_path != "/products":
            raise AppError("Social OAuth redirect is not allowed", 503)
        return self.settings.frontend_social_redirect_path

    def _frontend_redirect(self, path: str, status: str) -> str:
        if status not in {"connected", "denied", "failed"}:
            raise AppError("TikTok OAuth result is invalid", 500)
        base = self.settings.social_frontend_base_url.rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise AppError("Social frontend redirect is not allowed", 503)
        return f"{base}{path}?{urlencode({'tiktok_oauth': status})}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
