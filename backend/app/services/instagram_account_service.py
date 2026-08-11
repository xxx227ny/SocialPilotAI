from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import OAuthSession, Product, SocialAccount
from app.providers.instagram_provider import (
    INSTAGRAM_ACCOUNT_TYPES,
    INSTAGRAM_SCOPES,
    InstagramProvider,
    InstagramProviderError,
)
from app.repositories.social import SocialRepository
from app.schemas.social import (
    InstagramConnectRead,
    InstagramDisconnectRead,
    SocialAccountRead,
)
from app.services.social_security import (
    TokenCipher,
    digest_oauth_state,
    generate_oauth_state,
)

INSTAGRAM_OAUTH_SESSION_LIFETIME = timedelta(minutes=10)


class InstagramAccountService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        provider: InstagramProvider | None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.repository = SocialRepository(session)

    def connect(
        self, product_id: int, *, browser_session_digest: str
    ) -> InstagramConnectRead:
        self._require_enabled()
        self._require_product(product_id)
        cipher = TokenCipher(self.settings)
        state = generate_oauth_state()
        expires_at = datetime.now(UTC) + INSTAGRAM_OAUTH_SESSION_LIFETIME
        session = OAuthSession(
            product_id=product_id,
            platform="instagram",
            state_digest=digest_oauth_state(state),
            browser_session_digest=browser_session_digest,
            # The shared column stores an encrypted internal nonce. Instagram Login
            # does not advertise PKCE support and no PKCE claim is made here.
            pkce_verifier_ciphertext=cipher.encrypt(secrets.token_urlsafe(48)),
            redirect_path=self._safe_redirect_path(),
            expires_at=expires_at,
        )
        self.session.add(session)
        self.session.commit()
        return InstagramConnectRead(
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
        oauth_session = self.repository.get_oauth_session(digest_oauth_state(state))
        if oauth_session is None or oauth_session.platform != "instagram":
            raise AppError("Instagram OAuth state is invalid", 400)
        if not hmac.compare_digest(
            oauth_session.browser_session_digest, browser_session_digest
        ):
            raise AppError("Instagram OAuth browser session does not match", 400)
        if oauth_session.consumed_at is not None:
            raise AppError("Instagram OAuth state has already been used", 409)
        if _as_utc(oauth_session.expires_at) <= datetime.now(UTC):
            raise AppError("Instagram OAuth state has expired", 410)
        oauth_session.consumed_at = datetime.now(UTC)
        self.session.commit()
        if error is not None:
            return self._frontend_redirect(oauth_session.redirect_path, "denied")
        if not code:
            return self._frontend_redirect(oauth_session.redirect_path, "failed")
        cipher = TokenCipher(self.settings)
        try:
            # Decryption authenticates the internal flow nonce.
            # It is never sent to Meta.
            cipher.decrypt(oauth_session.pkce_verifier_ciphertext)
            short = await self._provider().exchange_code(code=code)
            if set(short.scopes) != set(INSTAGRAM_SCOPES) or len(short.scopes) != len(
                INSTAGRAM_SCOPES
            ):
                raise InstagramProviderError("instagram_scope_mismatch")
            long_token = await self._provider().exchange_long_lived_token(
                short.access_token
            )
            profile = await self._provider().get_professional_profile(
                user_id=short.user_id, access_token=long_token.access_token
            )
            if (
                profile.account_id != short.user_id
                or profile.account_type not in INSTAGRAM_ACCOUNT_TYPES
            ):
                raise InstagramProviderError("professional_account_required")
        except (InstagramProviderError, AppError):
            return self._frontend_redirect(oauth_session.redirect_path, "failed")

        account = self.repository.get_account_by_provider_identity(
            oauth_session.product_id, "instagram", profile.account_id
        )
        encrypted_access_token = cipher.encrypt(long_token.access_token)
        if account is None:
            account = SocialAccount(
                product_id=oauth_session.product_id,
                platform="instagram",
                provider_account_id=profile.account_id,
                display_name=profile.username,
                scopes=list(short.scopes),
                access_token_ciphertext=encrypted_access_token,
                refresh_token_ciphertext=None,
                token_expires_at=long_token.expires_at,
                connection_status="CONNECTED",
                encryption_key_id=cipher.key_id,
            )
            self.session.add(account)
        else:
            account.display_name = profile.username
            account.scopes = list(short.scopes)
            account.access_token_ciphertext = encrypted_access_token
            account.refresh_token_ciphertext = None
            account.token_expires_at = long_token.expires_at
            account.connection_status = "CONNECTED"
            account.encryption_key_id = cipher.key_id
            account.disconnected_at = None
        self.session.commit()
        return self._frontend_redirect(oauth_session.redirect_path, "connected")

    def disconnect(
        self, account_id: int, *, product_id: int
    ) -> InstagramDisconnectRead:
        self._require_enabled()
        account = self.repository.get_account(account_id)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "instagram"
        ):
            raise AppError("Instagram account not found", 404)
        account.access_token_ciphertext = None
        account.refresh_token_ciphertext = None
        account.token_expires_at = None
        account.connection_status = "DISCONNECTED"
        account.disconnected_at = datetime.now(UTC)
        self.session.commit()
        return InstagramDisconnectRead(
            account=SocialAccountRead.model_validate(account)
        )

    def _require_enabled(self) -> None:
        if not self.settings.enable_instagram_account_binding:
            raise AppError("Instagram account binding is disabled by the server", 503)

    def _provider(self) -> InstagramProvider:
        if self.provider is None:
            raise AppError("Instagram OAuth provider is unavailable", 503)
        return self.provider

    def _require_product(self, product_id: int) -> Product:
        product = self.session.get(Product, product_id)
        if product is None:
            raise AppError("Product not found", 404)
        return product

    def _safe_redirect_path(self) -> str:
        if self.settings.frontend_social_redirect_path != "/products":
            raise AppError("Social OAuth redirect is not allowed", 503)
        return self.settings.frontend_social_redirect_path

    def _frontend_redirect(self, path: str, status: str) -> str:
        if status not in {"connected", "denied", "failed"}:
            raise AppError("Instagram OAuth result is invalid", 500)
        base = self.settings.social_frontend_base_url.rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise AppError("Social frontend redirect is not allowed", 503)
        return f"{base}{path}?{urlencode({'instagram_oauth': status})}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
