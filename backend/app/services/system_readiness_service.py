import json
import os
import sys
from ctypes import byref, wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

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
    ExecutionWorkerSystemComponentRead,
    SystemComponentRead,
    SystemReadinessRead,
)
from app.services.database_migration_service import HEAD_REVISION
from app.services.social_security import TokenCipher

WorkerProcessState = Literal["running", "missing", "unknown"]


def _windows_process_state(pid: int) -> WorkerProcessState:
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return (
            "missing"
            if ctypes.get_last_error() == error_invalid_parameter
            else "unknown"
        )
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, byref(exit_code)):
            return "unknown"
        return "running" if exit_code.value == still_active else "missing"
    finally:
        kernel32.CloseHandle(handle)


def _process_state(pid: int) -> WorkerProcessState:
    if sys.platform == "win32":
        try:
            return _windows_process_state(pid)
        except (OSError, RuntimeError, TypeError, ValueError):
            return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "missing"
    except (PermissionError, OSError):
        return "unknown"
    return "running"


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
        instagram_ready = bool(
            self.settings.enable_instagram_account_binding
            and self._text(self.settings.instagram_app_id)
            and self._secret(self.settings.instagram_app_secret)
            and self._valid_http_uri(self.settings.instagram_oauth_redirect_uri)
            and self._valid_graph_version(self.settings.instagram_graph_api_version)
            and self._valid_token_cipher()
        )
        database_ready, revision_status, revision = self._database_readiness()
        artifact_ready = self._artifact_storage_ready()
        worker_ready, worker_status, worker_reason = (
            self._execution_worker_readiness()
        )

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
            meta_instagram=SystemComponentRead(
                ready=instagram_ready,
                message=(
                    "Meta / Instagram配置已就绪；仅表示本机配置完整，不代表"
                    "App Review、Advanced Access或真实账号绑定已通过。"
                    if instagram_ready
                    else (
                        "Meta / Instagram未就绪：请配置独立Gate、App ID、"
                        "App Secret、Redirect URI、固定Graph API版本和"
                        "社交Token加密密钥。"
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
            execution_worker=ExecutionWorkerSystemComponentRead(
                ready=worker_ready,
                status=worker_status,
                message=(
                    "Execution Worker is running and its local heartbeat is current."
                    if worker_reason == "healthy"
                    else (
                        "Execution Worker heartbeat is stale; restart "
                        "SocialPilotAI safely."
                        if worker_reason == "stale"
                        else (
                            "Execution Worker identity could not be safely confirmed; "
                            "restart SocialPilotAI safely."
                            if worker_reason == "unknown"
                            else (
                                "Execution Worker is not running; start "
                                "SocialPilotAI again."
                            )
                        )
                    )
                ),
            ),
        )

    def _execution_worker_readiness(self) -> tuple[bool, str, str]:
        configured = self._text(self.settings.execution_worker_status_file)
        if not configured:
            return False, "not_running", "missing"
        path = Path(configured)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("state") != "healthy":
                return False, "not_running", "missing"
            updated = datetime.fromisoformat(str(payload["updated_at_utc"]))
            if updated.tzinfo is None:
                return False, "stale", "stale"
            age = (datetime.now(UTC) - updated.astimezone(UTC)).total_seconds()
            if age < -5 or age > self.settings.execution_worker_stale_seconds:
                return False, "stale", "stale"
            pid = int(payload["pid"])
            if pid <= 0:
                return False, "not_running", "missing"
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False, "not_running", "missing"
        process_state = _process_state(pid)
        if process_state == "missing":
            return False, "not_running", "missing"
        if process_state == "unknown":
            return False, "not_running", "unknown"
        return True, "healthy", "healthy"

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
    def _valid_http_uri(value: object) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _valid_graph_version(value: object) -> bool:
        if not isinstance(value, str) or not value.startswith("v"):
            return False
        major, dot, minor = value[1:].partition(".")
        return dot == "." and major.isdigit() and minor.isdigit()

    @staticmethod
    def _secret(value: object) -> bool:
        if value is None or not hasattr(value, "get_secret_value"):
            return False
        secret = value.get_secret_value()  # type: ignore[union-attr]
        return isinstance(secret, str) and bool(secret.strip())

    @staticmethod
    def _text(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""
