from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import OAuthSession, SocialAccount
from app.providers.pinterest_provider import (
    PINTEREST_SCOPES,
    PinterestProvider,
    PinterestProviderError,
)
from app.repositories.product import ProductRepository
from app.repositories.social import SocialRepository
from app.schemas.social import (
    PinterestConnectRead,
    PinterestDisconnectRead,
    SocialAccountRead,
)
from app.services.social_security import (
    TokenCipher,
    digest_oauth_state,
    generate_oauth_state,
)

PINTEREST_OAUTH_SESSION_LIFETIME = timedelta(minutes=10)


class PinterestAccountService:
    def __init__(
        self, session: Session, settings: Settings, provider: PinterestProvider | None
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.repository = SocialRepository(session)
        self.products = ProductRepository(session)

    def connect(
        self, product_id: int, *, browser_session_digest: str
    ) -> PinterestConnectRead:
        self._require_enabled()
        if self.products.get(product_id) is None:
            raise AppError("Product not found", 404)
        cipher = TokenCipher(self.settings)
        state = generate_oauth_state()
        expires_at = datetime.now(UTC) + PINTEREST_OAUTH_SESSION_LIFETIME
        self.session.add(
            OAuthSession(
                workspace_id=self.repository.workspace_id,
                product_id=product_id,
                platform="pinterest",
                state_digest=digest_oauth_state(state),
                browser_session_digest=browser_session_digest,
                pkce_verifier_ciphertext=cipher.encrypt(secrets.token_urlsafe(48)),
                redirect_path=self._safe_redirect_path(),
                expires_at=expires_at,
            )
        )
        self.session.commit()
        return PinterestConnectRead(
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
        if oauth is None or oauth.platform != "pinterest":
            raise AppError("Pinterest OAuth state is invalid", 400)
        if not hmac.compare_digest(
            oauth.browser_session_digest, browser_session_digest
        ):
            raise AppError("Pinterest OAuth browser session does not match", 400)
        if oauth.consumed_at is not None:
            raise AppError("Pinterest OAuth state has already been used", 409)
        if _as_utc(oauth.expires_at) <= datetime.now(UTC):
            raise AppError("Pinterest OAuth state has expired", 410)
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
            if tuple(sorted(token.scopes)) != PINTEREST_SCOPES or len(
                token.scopes
            ) != len(PINTEREST_SCOPES):
                raise PinterestProviderError("pinterest_scope_mismatch")
            user = await self._provider().get_user_account(
                access_token=token.access_token
            )
        except (PinterestProviderError, AppError):
            return self._frontend_redirect(oauth.redirect_path, "failed")
        account = self.repository.get_account_by_provider_identity(
            oauth.product_id, "pinterest", user.account_id
        )
        values = {
            "display_name": user.display_name,
            "scopes": list(PINTEREST_SCOPES),
            "access_token_ciphertext": cipher.encrypt(token.access_token),
            "refresh_token_ciphertext": cipher.encrypt(token.refresh_token)
            if token.refresh_token
            else None,
            "token_expires_at": token.access_token_expires_at,
            "refresh_token_expires_at": token.refresh_token_expires_at,
            "connection_status": "CONNECTED",
            "encryption_key_id": cipher.key_id,
            "disconnected_at": None,
        }
        if account is None:
            account = SocialAccount(
                workspace_id=oauth.workspace_id,
                product_id=oauth.product_id,
                platform="pinterest",
                provider_account_id=user.account_id,
                **values,
            )
            self.session.add(account)
        else:
            account.workspace_id = oauth.workspace_id
            for name, value in values.items():
                setattr(account, name, value)
        self.session.commit()
        return self._frontend_redirect(oauth.redirect_path, "connected")

    def disconnect(
        self, account_id: int, *, product_id: int
    ) -> PinterestDisconnectRead:
        self._require_enabled()
        account = self.repository.get_account(account_id)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "pinterest"
        ):
            raise AppError("Pinterest account not found", 404)
        account.access_token_ciphertext = None
        account.refresh_token_ciphertext = None
        account.token_expires_at = None
        account.refresh_token_expires_at = None
        account.connection_status = "DISCONNECTED"
        account.disconnected_at = datetime.now(UTC)
        self.session.commit()
        return PinterestDisconnectRead(
            account=SocialAccountRead.model_validate(account)
        )

    def _require_enabled(self) -> None:
        if not self.settings.enable_pinterest_account_binding:
            raise AppError("Pinterest account binding is disabled by the server", 503)

    def _provider(self) -> PinterestProvider:
        if self.provider is None:
            raise AppError("Pinterest OAuth provider is unavailable", 503)
        return self.provider

    def _safe_redirect_path(self) -> str:
        if self.settings.frontend_social_redirect_path != "/products":
            raise AppError("Social OAuth redirect is not allowed", 503)
        return self.settings.frontend_social_redirect_path

    def _frontend_redirect(self, path: str, status: str) -> str:
        if status not in {"connected", "denied", "failed"}:
            raise AppError("Pinterest OAuth result is invalid", 500)
        base = self.settings.social_frontend_base_url.rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise AppError("Social frontend redirect is not allowed", 503)
        return f"{base}{path}?{urlencode({'pinterest_oauth': status})}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
