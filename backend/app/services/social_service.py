from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import OAuthSession, Product, PublishTask, SocialAccount
from app.models.video_render_artifact import VideoRenderArtifact
from app.providers.youtube_provider import (
    YOUTUBE_SCOPES,
    YouTubeProvider,
    YouTubeProviderError,
    YouTubeUploadUncertain,
)
from app.repositories.product import ProductRepository
from app.repositories.social import SocialRepository
from app.schemas.social import (
    DisconnectRead,
    PublishArtifactCandidateRead,
    PublishExecutionRead,
    PublishTaskRead,
    SocialAccountRead,
    YouTubeConnectRead,
    YouTubePreflightRead,
    YouTubePublishingMetadata,
    YouTubePublishRequest,
)
from app.services.social_security import (
    TokenCipher,
    digest_oauth_state,
    generate_oauth_state,
    generate_pkce_pair,
    validated_social_frontend_origin,
)
from app.services.video_artifact_storage import VideoArtifactStorage
from app.services.video_render_operation_service import (
    VerifiedVideoArtifact,
    VideoArtifactAccessService,
)

OAUTH_SESSION_LIFETIME = timedelta(minutes=10)
TOKEN_REFRESH_SKEW = timedelta(seconds=60)
_refresh_locks: dict[int, asyncio.Lock] = {}


class SocialAuthorizationError(Exception):
    def __init__(
        self,
        safe_error_code: str,
        status_code: int = 409,
        *,
        external_call: bool = False,
    ) -> None:
        self.safe_error_code = safe_error_code
        self.status_code = status_code
        self.external_call = external_call
        super().__init__(safe_error_code)


class SocialAccountService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        provider: YouTubeProvider | None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.repository = SocialRepository(session)
        self.products = ProductRepository(session)

    def connect(
        self, product_id: int, *, browser_session_digest: str
    ) -> YouTubeConnectRead:
        self._require_binding_enabled()
        self._require_product(product_id)
        cipher = TokenCipher(self.settings)
        redirect_path = self._safe_redirect_path()
        state = generate_oauth_state()
        verifier, challenge = generate_pkce_pair()
        expires_at = datetime.now(UTC) + OAUTH_SESSION_LIFETIME
        oauth_session = OAuthSession(
            workspace_id=self.repository.workspace_id,
            product_id=product_id,
            platform="youtube",
            state_digest=digest_oauth_state(state),
            browser_session_digest=browser_session_digest,
            pkce_verifier_ciphertext=cipher.encrypt(verifier),
            redirect_path=redirect_path,
            expires_at=expires_at,
        )
        self.session.add(oauth_session)
        self.session.commit()
        return YouTubeConnectRead(
            authorization_url=self._provider().authorization_url(
                state=state, code_challenge=challenge
            ),
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
        self._require_binding_enabled()
        oauth_session = self.repository.get_oauth_session(digest_oauth_state(state))
        if oauth_session is None or oauth_session.platform != "youtube":
            raise AppError("OAuth state is invalid", 400)
        if not hmac.compare_digest(
            oauth_session.browser_session_digest, browser_session_digest
        ):
            raise AppError("OAuth browser session does not match", 400)
        if oauth_session.consumed_at is not None:
            raise AppError("OAuth state has already been used", 409)
        if _as_utc(oauth_session.expires_at) <= datetime.now(UTC):
            raise AppError("OAuth state has expired", 410)
        oauth_session.consumed_at = datetime.now(UTC)
        self.session.commit()
        if error is not None:
            return self._frontend_redirect(oauth_session.redirect_path, "denied")
        if not code:
            raise AppError("OAuth authorization code is missing", 400)
        cipher = TokenCipher(self.settings)
        verifier = cipher.decrypt(oauth_session.pkce_verifier_ciphertext)
        try:
            tokens = await self._provider().exchange_code(
                code=code, code_verifier=verifier
            )
            channel = await self._provider().get_channel(tokens.access_token)
        except YouTubeProviderError as exc:
            raise _provider_app_error(exc) from exc
        granted_scopes = sorted(set(tokens.scopes))
        if not set(YOUTUBE_SCOPES).issubset(granted_scopes):
            raise AppError("Required YouTube permissions were not granted", 403)
        account = self.repository.get_account_by_channel(
            oauth_session.product_id, channel.channel_id
        )
        if account is None:
            account = SocialAccount(
                workspace_id=oauth_session.workspace_id,
                product_id=oauth_session.product_id,
                platform="youtube",
                provider_account_id=channel.channel_id,
                display_name=channel.display_name,
                scopes=granted_scopes,
                access_token_ciphertext=cipher.encrypt(tokens.access_token),
                refresh_token_ciphertext=(
                    cipher.encrypt(tokens.refresh_token)
                    if tokens.refresh_token is not None
                    else None
                ),
                token_expires_at=tokens.expires_at,
                connection_status="CONNECTED",
                encryption_key_id=cipher.key_id,
            )
            self.session.add(account)
        else:
            account.workspace_id = oauth_session.workspace_id
            account.display_name = channel.display_name
            account.scopes = granted_scopes
            account.access_token_ciphertext = cipher.encrypt(tokens.access_token)
            if tokens.refresh_token is not None:
                account.refresh_token_ciphertext = cipher.encrypt(tokens.refresh_token)
            account.token_expires_at = tokens.expires_at
            account.connection_status = "CONNECTED"
            account.encryption_key_id = cipher.key_id
            account.disconnected_at = None
        self.session.commit()
        return self._frontend_redirect(oauth_session.redirect_path, "connected")

    def list_accounts(self, product_id: int) -> list[SocialAccountRead]:
        self._require_product(product_id)
        return [
            SocialAccountRead.model_validate(account)
            for account in self.repository.list_accounts(product_id)
        ]

    def get_account(self, account_id: int, product_id: int) -> SocialAccountRead:
        account = self._account(account_id, product_id)
        return SocialAccountRead.model_validate(account)

    async def disconnect(
        self,
        account_id: int,
        *,
        product_id: int,
        revoke_google_authorization: bool,
    ) -> DisconnectRead:
        self._require_binding_enabled()
        account = self._account(account_id, product_id)
        cipher = TokenCipher(self.settings)
        revoked = False
        if revoke_google_authorization:
            ciphertext = (
                account.refresh_token_ciphertext or account.access_token_ciphertext
            )
            if not ciphertext:
                raise AppError("Stored Google authorization is unavailable", 409)
            try:
                await self._provider().revoke_token(cipher.decrypt(ciphertext))
            except YouTubeProviderError as exc:
                raise _provider_app_error(exc) from exc
            revoked = True
        account.access_token_ciphertext = None
        account.refresh_token_ciphertext = None
        account.token_expires_at = None
        account.connection_status = "DISCONNECTED"
        account.disconnected_at = datetime.now(UTC)
        self.session.commit()
        return DisconnectRead(
            account=SocialAccountRead.model_validate(account),
            google_authorization_revoked=revoked,
        )

    def _require_binding_enabled(self) -> None:
        if not self.settings.enable_social_account_binding:
            raise AppError("Social account binding is disabled by the server", 503)

    def _provider(self) -> YouTubeProvider:
        if self.provider is None:
            raise AppError("YouTube OAuth provider is unavailable", 503)
        return self.provider

    def _require_product(self, product_id: int) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise AppError("Product not found", 404)
        return product

    def _account(self, account_id: int, product_id: int) -> SocialAccount:
        account = self.repository.get_account(account_id)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "youtube"
        ):
            raise AppError("Social account not found", 404)
        return account

    def _safe_redirect_path(self) -> str:
        path = self.settings.frontend_social_redirect_path
        if path != "/products":
            raise AppError("Social OAuth redirect is not allowed", 503)
        return path

    def _frontend_redirect(self, path: str, status: str) -> str:
        base = validated_social_frontend_origin(self.settings)
        return f"{base}{path}?{urlencode({'youtube_oauth': status})}"


class YouTubePublishingService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        provider: YouTubeProvider | None,
        storage: VideoArtifactStorage,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.storage = storage
        self.repository = SocialRepository(session)
        self.products = ProductRepository(session)
        self.artifact_access = VideoArtifactAccessService(session, storage)

    def list_candidates(self, product_id: int) -> list[PublishArtifactCandidateRead]:
        self._require_product(product_id)
        statement = (
            select(VideoRenderArtifact)
            .join(VideoRenderArtifact.video_render_task)
            .where(VideoRenderArtifact.storage_path.is_not(None))
            .order_by(VideoRenderArtifact.id)
        )
        candidates: list[PublishArtifactCandidateRead] = []
        for artifact in self.session.scalars(statement).all():
            try:
                verified, project = self._verify_artifact(product_id, artifact.id)
            except AppError:
                continue
            candidates.append(_candidate(verified, project))
        return candidates

    def preflight(
        self,
        product_id: int,
        data: YouTubePublishingMetadata,
        *,
        expires_at: datetime | None = None,
    ) -> YouTubePreflightRead:
        self._require_publishing_enabled()
        self._require_product(product_id)
        account = self._require_account(product_id, data.social_account_id)
        verified, project = self._verify_artifact(product_id, data.artifact_id)
        missing: list[str] = []
        if account.connection_status != "CONNECTED":
            missing.append("YouTube account is not connected")
        if account.access_token_ciphertext is None:
            missing.append("YouTube authorization is unavailable")
        try:
            TokenCipher(self.settings)
        except AppError:
            missing.append("Social token encryption is not configured")
        if data.made_for_kids is None:
            missing.append("Made-for-kids selection is required")
        preflight_expires_at = expires_at or (
            datetime.now(UTC) + OAUTH_SESSION_LIFETIME
        )
        normalized_expiry = _as_utc(preflight_expires_at)
        if normalized_expiry is None:
            raise AppError("YouTube publishing preflight expiry is invalid", 409)
        if normalized_expiry <= datetime.now(UTC):
            raise AppError("YouTube publishing preflight has expired", 409)
        if normalized_expiry > datetime.now(UTC) + OAUTH_SESSION_LIFETIME:
            raise AppError("YouTube publishing preflight expiry is invalid", 409)
        input_digest = self._preflight_digest(
            product_id,
            account,
            verified,
            project,
            data,
        )
        digest = _digest(
            {
                "contract": "youtube-private-preflight-v1",
                "input_digest": input_digest,
                "expires_at": normalized_expiry.isoformat(),
            }
        )
        ready = not missing
        task = verified.artifact.video_render_task
        return YouTubePreflightRead(
            status="READY" if ready else "BLOCKED",
            ready=ready,
            missing_requirements=missing,
            input_digest=input_digest,
            preflight_digest=digest,
            expires_at=normalized_expiry,
            product_id=product_id,
            social_account_id=account.id,
            channel_id=account.provider_account_id,
            artifact_id=verified.artifact.id,
            render_task_id=task.id,
            video_project_id=project.id,
            copy_matrix_id=project.copy_matrix_id,
            privacy_status="private",
            synthetic_media=True,
            notify_subscribers=False,
        )

    async def publish(
        self, product_id: int, data: YouTubePublishRequest
    ) -> PublishExecutionRead:
        self._require_publishing_enabled()
        preflight = self.preflight(
            product_id, data, expires_at=data.preflight_expires_at
        )
        if not preflight.ready:
            raise AppError("YouTube publishing preflight is blocked", 409)
        if preflight.preflight_digest != data.preflight_digest:
            raise AppError("YouTube publishing preflight has changed", 409)
        request_digest = self._request_digest(product_id, data)
        storage_key = self.repository.scoped_idempotency_key(data.idempotency_key)
        existing = self.repository.get_publish_task_by_key(storage_key)
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AppError("Idempotency key was used for another request", 409)
            return PublishExecutionRead(
                task=PublishTaskRead.model_validate(existing),
                reused=True,
                external_call=False,
            )
        task = PublishTask(
            workspace_id=self.repository.workspace_id,
            product_id=product_id,
            social_account_id=data.social_account_id,
            artifact_id=data.artifact_id,
            platform="youtube",
            idempotency_key=storage_key,
            request_digest=request_digest,
            preflight_digest=data.preflight_digest,
            title=data.title,
            description=data.description,
            tags=data.tags,
            privacy_status="private",
            made_for_kids=bool(data.made_for_kids),
            synthetic_media=True,
            notify_subscribers=False,
            status="CREATED",
        )
        self.session.add(task)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.get_publish_task_by_key(storage_key)
            if concurrent is None or concurrent.request_digest != request_digest:
                raise AppError(
                    "Publish request conflicts with an existing task", 409
                ) from None
            return PublishExecutionRead(
                task=PublishTaskRead.model_validate(concurrent),
                reused=True,
                external_call=False,
            )
        verified, _ = self._verify_artifact(product_id, data.artifact_id)
        account = self._require_account(product_id, data.social_account_id)
        try:
            access_token = await self._access_token(account)
        except SocialAuthorizationError as exc:
            task.status = "FAILED"
            task.uncertain = False
            task.safe_error_code = exc.safe_error_code
            task.completed_at = datetime.now(UTC)
            self.session.commit()
            return PublishExecutionRead(
                task=PublishTaskRead.model_validate(task),
                reused=False,
                external_call=exc.external_call,
            )
        task.status = "UPLOADING"
        task.submitted_at = datetime.now(UTC)
        self.session.commit()
        try:
            result = await self._provider().upload_video(
                access_token=access_token,
                path=verified.path,
                content_type=verified.content_type,
                title=data.title,
                description=data.description,
                tags=data.tags,
                made_for_kids=bool(data.made_for_kids),
            )
        except YouTubeUploadUncertain as exc:
            cipher = TokenCipher(self.settings)
            task.status = "SUBMIT_UNKNOWN"
            task.uncertain = True
            task.safe_error_code = exc.safe_error_code
            task.resumable_session_ciphertext = cipher.encrypt(exc.session_uri)
        except YouTubeProviderError as exc:
            task.status = "SUBMIT_UNKNOWN" if exc.uncertain else "FAILED"
            task.uncertain = exc.uncertain
            task.safe_error_code = exc.safe_error_code
            if not exc.uncertain:
                task.completed_at = datetime.now(UTC)
        except Exception:
            task.status = "SUBMIT_UNKNOWN"
            task.uncertain = True
            task.safe_error_code = "upload_result_uncertain"
        else:
            task.provider_video_id = result.video_id
            task.status = "SUBMITTED"
            task.uncertain = False
            task.safe_error_code = None
        self.session.commit()
        return PublishExecutionRead(
            task=PublishTaskRead.model_validate(task),
            reused=False,
            external_call=True,
        )

    def get_task(self, task_id: int, product_id: int) -> PublishTaskRead:
        task = self._require_task(task_id, product_id)
        return PublishTaskRead.model_validate(task)

    def list_tasks(self, product_id: int) -> list[PublishTaskRead]:
        self._require_product(product_id)
        return [
            PublishTaskRead.model_validate(task)
            for task in self.repository.list_publish_tasks(product_id)
        ]

    async def refresh(self, task_id: int, product_id: int) -> PublishExecutionRead:
        self._require_publishing_enabled()
        lock = _refresh_locks.setdefault(task_id, asyncio.Lock())
        if lock.locked():
            raise AppError("Publish task refresh is already running", 409)
        async with lock:
            task = self._require_task(task_id, product_id)
            if task.status not in {"SUBMITTED", "PROCESSING"}:
                raise AppError("Publish task cannot be refreshed", 409)
            if not task.provider_video_id:
                raise AppError("Provider video identity is unavailable", 409)
            account = self._require_account(task.product_id, task.social_account_id)
            try:
                access_token = await self._access_token(account)
                result = await self._provider().get_video_status(
                    access_token=access_token,
                    video_id=task.provider_video_id,
                )
            except SocialAuthorizationError as exc:
                raise AppError(
                    "YouTube authorization is unavailable", exc.status_code
                ) from exc
            except YouTubeProviderError as exc:
                raise _provider_app_error(exc) from exc
            task.status = result.status
            task.safe_error_code = result.safe_error_code
            if result.status in {"SUCCEEDED", "FAILED"}:
                task.completed_at = datetime.now(UTC)
            self.session.commit()
            return PublishExecutionRead(
                task=PublishTaskRead.model_validate(task),
                reused=True,
                external_call=True,
            )

    async def _access_token(self, account: SocialAccount) -> str:
        if account.access_token_ciphertext is None:
            raise SocialAuthorizationError("authorization_unavailable")
        try:
            cipher = TokenCipher(self.settings)
        except AppError as exc:
            raise SocialAuthorizationError(
                "authorization_configuration_error", exc.status_code
            ) from exc
        try:
            access_token = cipher.decrypt(account.access_token_ciphertext)
        except AppError as exc:
            raise SocialAuthorizationError(
                "authorization_decryption_failed", exc.status_code
            ) from exc
        expires_at = _as_utc(account.token_expires_at)
        if expires_at is None or expires_at > datetime.now(UTC) + TOKEN_REFRESH_SKEW:
            return access_token
        if account.refresh_token_ciphertext is None:
            account.connection_status = "EXPIRED"
            self.session.commit()
            raise SocialAuthorizationError("authorization_expired")
        try:
            refresh_token = cipher.decrypt(account.refresh_token_ciphertext)
        except AppError as exc:
            raise SocialAuthorizationError(
                "authorization_decryption_failed", exc.status_code
            ) from exc
        try:
            tokens = await self._provider().refresh_access_token(refresh_token)
        except YouTubeProviderError as exc:
            account.connection_status = "EXPIRED"
            self.session.commit()
            safe_error_code = exc.safe_error_code
            if not safe_error_code.startswith("token_refresh_"):
                safe_error_code = f"token_refresh_{safe_error_code}"
            raise SocialAuthorizationError(
                safe_error_code,
                exc.status_code or 503,
                external_call=True,
            ) from exc
        account.access_token_ciphertext = cipher.encrypt(tokens.access_token)
        if tokens.refresh_token:
            account.refresh_token_ciphertext = cipher.encrypt(tokens.refresh_token)
        account.token_expires_at = tokens.expires_at
        account.connection_status = "CONNECTED"
        self.session.commit()
        return tokens.access_token

    def _verify_artifact(
        self, product_id: int, artifact_id: int
    ) -> tuple[VerifiedVideoArtifact, object]:
        verified = self.artifact_access.resolve_verified(artifact_id)
        task = verified.artifact.video_render_task
        project = task.video_project
        if project is None or project.product_id != product_id:
            raise AppError("Artifact does not belong to Product", 404)
        if project.platform != "YouTube Shorts":
            raise AppError("Artifact is not a YouTube Shorts video", 409)
        if verified.content_type not in {"video/mp4", "video/webm"}:
            raise AppError("Artifact video type is not supported", 409)
        return verified, project

    def _require_account(self, product_id: int, account_id: int) -> SocialAccount:
        account = self.repository.get_account(account_id)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "youtube"
        ):
            raise AppError("Social account not found for Product", 404)
        return account

    def _require_product(self, product_id: int) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise AppError("Product not found", 404)
        return product

    def _require_task(self, task_id: int, product_id: int) -> PublishTask:
        task = self.repository.get_publish_task(task_id)
        if task is None or task.product_id != product_id:
            raise AppError("Publish task not found for Product", 404)
        return task

    def _require_publishing_enabled(self) -> None:
        if not self.settings.enable_youtube_publishing:
            raise AppError("YouTube publishing is disabled by the server", 503)

    def _provider(self) -> YouTubeProvider:
        if self.provider is None:
            raise AppError("YouTube publishing provider is unavailable", 503)
        return self.provider

    def _preflight_digest(
        self,
        product_id: int,
        account: SocialAccount,
        verified: VerifiedVideoArtifact,
        project: object,
        data: YouTubePublishingMetadata,
    ) -> str:
        task = verified.artifact.video_render_task
        payload = {
            "contract": "youtube-private-publish-v1",
            "product_id": product_id,
            "account_id": account.id,
            "channel_id": account.provider_account_id,
            "artifact_id": verified.artifact.id,
            "render_task_id": task.id,
            "video_project_id": project.id,
            "copy_matrix_id": project.copy_matrix_id,
            "artifact_sha256": verified.sha256,
            "title": data.title,
            "artifact_size": verified.size_bytes,
            "artifact_content_type": verified.content_type,
            "description": data.description,
            "tags": data.tags,
            "privacy_status": "private",
            "made_for_kids": data.made_for_kids,
            "synthetic_media": True,
            "notify_subscribers": False,
        }
        return _digest(payload)

    @staticmethod
    def _request_digest(product_id: int, data: YouTubePublishRequest) -> str:
        return _digest(
            {
                "product_id": product_id,
                "account_id": data.social_account_id,
                "artifact_id": data.artifact_id,
                "title": data.title,
                "description": data.description,
                "tags": data.tags,
                "privacy_status": "private",
                "made_for_kids": data.made_for_kids,
                "synthetic_media": True,
                "notify_subscribers": False,
            }
        )


def _candidate(
    verified: VerifiedVideoArtifact, project: object
) -> PublishArtifactCandidateRead:
    artifact = verified.artifact
    task = artifact.video_render_task
    return PublishArtifactCandidateRead(
        artifact_id=artifact.id,
        render_task_id=task.id,
        video_project_id=project.id,
        copy_matrix_id=project.copy_matrix_id,
        content_type=verified.content_type,
        size_bytes=verified.size_bytes,
        sha256=verified.sha256,
        created_at=artifact.created_at,
    )


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _provider_app_error(exc: YouTubeProviderError) -> AppError:
    status = 503
    if exc.status_code in {400, 401, 403, 404, 408, 429}:
        status = exc.status_code
    return AppError(f"YouTube request failed: {exc.safe_error_code}", status)
