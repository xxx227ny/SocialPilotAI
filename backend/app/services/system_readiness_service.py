import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.providers.live_configuration import (
    qwen_provider_configured,
    wanx_provider_configured,
)
from app.schemas.system import (
    DatabaseSystemComponentRead,
    SystemComponentRead,
    SystemReadinessRead,
)
from app.services.database_migration_service import HEAD_REVISION
from app.services.social_security import TokenCipher


class SystemReadinessService:
    """Report local configuration state without resolving or calling Providers."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def get(self) -> SystemReadinessRead:
        qwen_ready = bool(
            qwen_provider_configured(self.settings)
            and self.settings.enable_strategy_execution
            and self.settings.enable_copy_execution
            and self.settings.enable_video_project_execution
        )
        wanx_ready = bool(
            wanx_provider_configured(self.settings)
            and self.settings.enable_video_render_execution
        )
        google_ready = bool(
            self._text(self.settings.google_oauth_client_id)
            and self._secret(self.settings.google_oauth_client_secret)
            and self._text(self.settings.google_oauth_redirect_uri)
            and self._valid_token_cipher()
            and self.settings.enable_social_account_binding
            and self.settings.enable_youtube_publishing
        )
        database_ready, revision_status, revision = self._database_readiness()
        artifact_ready = self._artifact_storage_ready()

        return SystemReadinessRead(
            backend=SystemComponentRead(
                ready=True,
                message="Backend已启动；外部操作仍需网页显式确认。",
            ),
            qwen=SystemComponentRead(
                ready=qwen_ready,
                message=(
                    "Qwen已就绪；Strategy、Copy和Video Blueprint执行前仍需费用确认。"
                    if qwen_ready
                    else (
                        "Qwen未就绪：请在backend/.env配置QWEN_API_KEY及所需"
                        "Workspace/Endpoint。"
                    )
                ),
            ),
            wanx=SystemComponentRead(
                ready=wanx_ready,
                message=(
                    "Wanx已就绪；创建RenderTask前仍需费用确认。"
                    if wanx_ready
                    else (
                        "Wanx未就绪：请在backend/.env配置WANX_API_KEY及"
                        "WANX_WORKSPACE_ID或WANX_ENDPOINT。"
                    )
                ),
            ),
            google_youtube=SystemComponentRead(
                ready=google_ready,
                message=(
                    "Google/YouTube已就绪；OAuth和Private发布只能由用户主动执行。"
                    if google_ready
                    else (
                        "Google/YouTube未就绪：请在backend/.env配置"
                        "GOOGLE_OAUTH_CLIENT_ID、GOOGLE_OAUTH_CLIENT_SECRET、"
                        "GOOGLE_OAUTH_REDIRECT_URI和SOCIAL_TOKEN_ENCRYPTION_KEY。"
                    )
                ),
            ),
            database=DatabaseSystemComponentRead(
                ready=database_ready,
                message=(
                    "数据库可用，且已验证为Alembic head。"
                    if database_ready
                    else (
                        "数据库需要安全迁移：请停止服务后运行start-socialpilotai.cmd。"
                        if revision_status == "upgrade_required"
                        else "数据库Revision无法安全验证，请查看本机Runtime日志。"
                    )
                ),
                revision_status=revision_status,
                revision=revision,
            ),
            artifact_storage=SystemComponentRead(
                ready=artifact_ready,
                message=(
                    "Artifact持久化目录可用。"
                    if artifact_ready
                    else "Artifact目录不可用：请检查本机Runtime目录权限。"
                ),
            ),
        )

    def _database_readiness(self) -> tuple[bool, str, str | None]:
        try:
            if self.session.scalar(text("SELECT 1")) != 1:
                return False, "unavailable", None
        except SQLAlchemyError:
            return False, "unavailable", None
        try:
            revision = self.session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        except SQLAlchemyError:
            return False, "upgrade_required", None
        if revision == HEAD_REVISION:
            return True, "head", revision
        return False, "upgrade_required", revision

    def _artifact_storage_ready(self) -> bool:
        configured = self._text(self.settings.video_artifact_storage_root)
        if not configured:
            return False
        path = Path(configured)
        return path.is_dir() and os.access(path, os.W_OK)

    def _valid_token_cipher(self) -> bool:
        try:
            TokenCipher(self.settings)
        except AppError:
            return False
        return True

    @staticmethod
    def _secret(value: object) -> bool:
        if value is None or not hasattr(value, "get_secret_value"):
            return False
        secret = value.get_secret_value()  # type: ignore[union-attr]
        return isinstance(secret, str) and bool(secret.strip())

    @staticmethod
    def _text(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""
