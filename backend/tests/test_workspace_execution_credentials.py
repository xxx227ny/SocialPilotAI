import hashlib

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.execution.contracts import ExecutionContext, HandlerResult
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.providers.live_configuration import effective_qwen_api_key
from app.schemas.execution import ExecutionJobCreate
from app.services.execution_queue_service import ExecutionQueueService

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

    def execute(
        self, context: ExecutionContext, payload: BaseModel
    ) -> HandlerResult:
        del context, payload
        self.observed.append(effective_qwen_api_key(self.settings))
        return HandlerResult.succeeded(provider_name="credential-probe")


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
    assert [job["id"] for job in second_list.json()] == [
        second_job.json()["job"]["id"]
    ]
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
