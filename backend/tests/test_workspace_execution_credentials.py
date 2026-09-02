import hashlib

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.provider_runtime import resolve_workspace_provider_runtime
from app.execution.contracts import ExecutionContext, HandlerResult
from app.execution.credential_context import current_execution_provider_runtime
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.providers.live_configuration import (
    effective_happyhorse_endpoint,
    effective_qwen_api_key,
    effective_qwen_endpoint,
    effective_qwen_tts_endpoint,
    effective_wanx_endpoint,
    effective_wanx_image_endpoint,
)
from app.schemas.execution import ExecutionJobCreate
from app.services.execution_queue_service import ExecutionQueueService
from app.services.provider_credential_service import ProviderCredentialService

PASSWORD = "strong-user-password"
USER_API_KEY = "sk-workspace-owned-key-123456"


class CredentialProbeInput(BaseModel):
    value: str


class CredentialProbeHandler:
    job_type = "test.workspace-credential"
    input_schema = CredentialProbeInput

    def __init__(self, settings: Settings, observed: list[str]) -> None:
        self.settings = settings
        self.observed = observed

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        del context, payload
        self.observed.append(effective_qwen_api_key(self.settings))
        return HandlerResult.succeeded(provider_name="credential-probe")


class ProviderProfileProbeHandler:
    job_type = "test.workspace-provider-profile"
    input_schema = CredentialProbeInput

    def __init__(self, settings: Settings, observed: list[dict[str, object]]) -> None:
        self.settings = settings
        self.observed = observed

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        del context, payload
        runtime = current_execution_provider_runtime()
        self.observed.append(
            {
                "api_key": effective_qwen_api_key(self.settings),
                "qwen": effective_qwen_endpoint(self.settings),
                "wanx": effective_wanx_endpoint(self.settings),
                "image": effective_wanx_image_endpoint(self.settings),
                "tts": effective_qwen_tts_endpoint(self.settings),
                "happyhorse": effective_happyhorse_endpoint(self.settings),
                "workspace_id": (
                    runtime.provider_workspace_id if runtime is not None else None
                ),
            }
        )
        return HandlerResult.succeeded(provider_name="provider-profile-probe")


def product_settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_session_ttl_seconds=3600,
        user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


def job_request() -> dict[str, object]:
    return {
        "job_type": "test.manual",
        "source_type": "product",
        "source_id": 1,
        "input_digest": hashlib.sha256(b"same-input").hexdigest(),
        "idempotency_key": "same-user-facing-key",
        "input_payload": {"value": "safe"},
    }


def test_users_can_create_same_idempotency_key_without_seeing_each_others_jobs(
    client: TestClient,
) -> None:
    settings = product_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    first_account = register(client, "first@example.com")
    first_job = client.post("/api/v1/execution-jobs", json=job_request())
    client.post("/api/v1/auth/logout")

    second_account = register(client, "second@example.com")
    second_job = client.post("/api/v1/execution-jobs", json=job_request())
    second_list = client.get("/api/v1/execution-jobs")
    first_job_from_second_user = client.get(
        f"/api/v1/execution-jobs/{first_job.json()['job']['id']}"
    )

    assert first_job.status_code == 201
    assert second_job.status_code == 201
    assert first_account["workspace_id"] != second_account["workspace_id"]
    assert first_job.json()["job"]["workspace_id"] == first_account["workspace_id"]
    assert second_job.json()["job"]["workspace_id"] == second_account["workspace_id"]
    assert [job["id"] for job in second_list.json()] == [second_job.json()["job"]["id"]]
    assert first_job_from_second_user.status_code == 404


def test_worker_uses_job_workspace_key_and_never_shared_fallback(
    db_session: Session,
) -> None:
    settings = Settings(
        _env_file=None,
        enable_user_auth=True,
        qwen_api_key="shared-key-must-not-be-used",
    )
    sessions = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    workspace_id = 901
    with sessions() as session:
        session.info["workspace_id"] = workspace_id
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=CredentialProbeHandler.job_type,
                source_type="test",
                source_id=1,
                input_digest=hashlib.sha256(b"credential-probe").hexdigest(),
                idempotency_key="workspace-credential-probe",
                input_payload={"value": "safe"},
            )
        )

    observed: list[str] = []
    resolved_workspaces: list[int | None] = []
    registry = ExecutionHandlerRegistry()
    registry.register(CredentialProbeHandler(settings, observed))

    def resolve(workspace: int | None) -> str | None:
        resolved_workspaces.append(workspace)
        return USER_API_KEY if workspace == workspace_id else None

    result = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="workspace-credential-worker",
        lease_seconds=10,
        heartbeat_interval_seconds=0.1,
        workspace_credential_resolver=resolve,
    ).run_once()

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert result.job_id == created.job.id
    assert resolved_workspaces == [workspace_id]
    assert observed == [USER_API_KEY]
    assert effective_qwen_api_key(settings) == ""


def test_worker_never_uses_unverified_workspace_key_or_shared_fallback(
    client: TestClient,
    db_session: Session,
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    settings = Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_session_ttl_seconds=3600,
        user_credential_encryption_key=encryption_key,
        qwen_api_key="shared-key-must-not-be-used",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    account = register(client, "unverified@example.com")
    workspace_id = int(account["workspace_id"])

    ProviderCredentialService(db_session, settings).set_dashscope_key(
        workspace_id, USER_API_KEY
    )
    db_session.commit()
    sessions = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    with sessions() as session:
        session.info["workspace_id"] = workspace_id
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=CredentialProbeHandler.job_type,
                source_type="test",
                source_id=1,
                input_digest=hashlib.sha256(b"unverified-probe").hexdigest(),
                idempotency_key="unverified-credential-probe",
                input_payload={"value": "safe"},
            )
        )

    observed: list[str] = []
    registry = ExecutionHandlerRegistry()
    registry.register(CredentialProbeHandler(settings, observed))

    def resolve(workspace: int | None) -> str | None:
        if workspace is None:
            return None
        with sessions() as session:
            return ProviderCredentialService(
                session, settings
            ).read_verified_dashscope_key(workspace)

    result = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="unverified-credential-worker",
        lease_seconds=10,
        heartbeat_interval_seconds=0.1,
        workspace_credential_resolver=resolve,
    ).run_once()

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert result.job_id == created.job.id
    assert observed == [""]
    assert effective_qwen_api_key(settings) == ""


def test_worker_binds_complete_workspace_profile_and_resets_it_after_job(
    db_session: Session,
) -> None:
    settings = Settings(
        _env_file=None,
        enable_user_auth=True,
        qwen_api_key="shared-key-must-not-be-used",
        qwen_endpoint="https://shared.invalid/compatible-mode/v1",
    )
    sessions = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    workspace_id = 902
    with sessions() as session:
        session.info["workspace_id"] = workspace_id
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=ProviderProfileProbeHandler.job_type,
                source_type="test",
                source_id=1,
                input_digest=hashlib.sha256(b"provider-profile-probe").hexdigest(),
                idempotency_key="workspace-provider-profile-probe",
                input_payload={"value": "safe"},
            )
        )

    runtime = resolve_workspace_provider_runtime(
        api_key=USER_API_KEY,
        region="cn-beijing",
        provider_workspace_id="workspace-902",
    )
    observed: list[dict[str, object]] = []
    registry = ExecutionHandlerRegistry()
    registry.register(ProviderProfileProbeHandler(settings, observed))

    result = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="provider-profile-worker",
        lease_seconds=10,
        heartbeat_interval_seconds=0.1,
        workspace_credential_resolver=lambda workspace: (
            runtime if workspace == workspace_id else None
        ),
    ).run_once()

    host = "https://workspace-902.cn-beijing.maas.aliyuncs.com"
    assert result.status == WorkerRunStatus.SUCCEEDED
    assert result.job_id == created.job.id
    assert observed == [
        {
            "api_key": USER_API_KEY,
            "qwen": f"{host}/compatible-mode/v1",
            "wanx": f"{host}/api/v1",
            "image": (f"{host}/api/v1/services/aigc/multimodal-generation/generation"),
            "tts": f"{host}/api/v1/services/audio/tts/SpeechSynthesizer",
            "happyhorse": f"{host}/api/v1",
            "workspace_id": "workspace-902",
        }
    ]
    assert current_execution_provider_runtime() is None
    assert effective_qwen_api_key(settings) == ""


def test_production_user_mode_rejects_shared_server_provider_key() -> None:
    with pytest.raises(ValueError, match="forbids shared provider keys"):
        Settings(
            _env_file=None,
            app_environment="production",
            enable_user_auth=True,
            user_auth_cookie_secure=True,
            user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
            qwen_api_key="shared-key-is-forbidden",
        )
