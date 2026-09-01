import hashlib
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.execution.contracts import ExecutionContext, HandlerResult
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    OAuthSession,
    Product,
    PublishTask,
    SocialAccount,
    Workspace,
)
from app.repositories.social import SocialRepository
from app.schemas.execution import ExecutionJobCreate
from app.services.execution_queue_service import ExecutionQueueService


class SocialIsolationProbeInput(BaseModel):
    own_account_id: int
    foreign_account_id: int


class SocialIsolationProbeHandler:
    job_type = "test.social-workspace-isolation"
    input_schema = SocialIsolationProbeInput

    def __init__(self, sessions, observed: list[tuple[bool, bool]]) -> None:
        self.sessions = sessions
        self.observed = observed

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        del context
        data = SocialIsolationProbeInput.model_validate(payload)
        with self.sessions() as session:
            social = SocialRepository(session)
            self.observed.append(
                (
                    social.get_account(data.own_account_id) is not None,
                    social.get_account(data.foreign_account_id) is not None,
                )
            )
        return HandlerResult.succeeded(provider_name="social-isolation-probe")


def _product(workspace_id: int, name: str) -> Product:
    return Product(
        workspace_id=workspace_id,
        name=name,
        category="Consumer Electronics",
        description="Workspace-owned product",
        selling_points=["Portable"],
        target_markets=["USA"],
    )


def _account(workspace_id: int, product_id: int, identity: str) -> SocialAccount:
    return SocialAccount(
        workspace_id=workspace_id,
        product_id=product_id,
        platform="youtube",
        provider_account_id=identity,
        display_name=identity,
        scopes=["youtube.upload"],
        access_token_ciphertext="encrypted",
        connection_status="CONNECTED",
        encryption_key_id="test-key",
    )


def _task(workspace_id: int, product_id: int, account_id: int, key: str) -> PublishTask:
    return PublishTask(
        workspace_id=workspace_id,
        product_id=product_id,
        social_account_id=account_id,
        artifact_id=1,
        platform="youtube",
        idempotency_key=key,
        request_digest=hashlib.sha256(key.encode()).hexdigest(),
        preflight_digest=hashlib.sha256(f"preflight:{key}".encode()).hexdigest(),
        title="Private upload",
        description="Private workspace publishing task",
        tags=["workspace"],
        privacy_status="private",
        made_for_kids=False,
        synthetic_media=True,
        notify_subscribers=False,
    )


def _seed_two_workspaces(db_session: Session) -> tuple[int, int, int, int]:
    first = Workspace(name="First Workspace")
    second = Workspace(name="Second Workspace")
    db_session.add_all([first, second])
    db_session.flush()
    first_product = _product(first.id, "First Product")
    second_product = _product(second.id, "Second Product")
    db_session.add_all([first_product, second_product])
    db_session.flush()
    first_account = _account(first.id, first_product.id, "first-channel")
    second_account = _account(second.id, second_product.id, "second-channel")
    db_session.add_all([first_account, second_account])
    db_session.flush()
    db_session.commit()
    return first.id, second.id, first_account.id, second_account.id


def test_social_records_are_private_to_the_current_workspace(
    db_session: Session,
) -> None:
    first_id, second_id, first_account_id, second_account_id = _seed_two_workspaces(
        db_session
    )
    first_account = db_session.get(SocialAccount, first_account_id)
    second_account = db_session.get(SocialAccount, second_account_id)
    assert first_account is not None and second_account is not None

    first_oauth = OAuthSession(
        workspace_id=first_id,
        product_id=first_account.product_id,
        platform="youtube",
        state_digest=hashlib.sha256(b"first-state").hexdigest(),
        browser_session_digest=hashlib.sha256(b"first-browser").hexdigest(),
        pkce_verifier_ciphertext="encrypted",
        redirect_path="/products",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    second_oauth = OAuthSession(
        workspace_id=second_id,
        product_id=second_account.product_id,
        platform="youtube",
        state_digest=hashlib.sha256(b"second-state").hexdigest(),
        browser_session_digest=hashlib.sha256(b"second-browser").hexdigest(),
        pkce_verifier_ciphertext="encrypted",
        redirect_path="/products",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    first_task = _task(
        first_id, first_account.product_id, first_account.id, "first-task"
    )
    second_task = _task(
        second_id, second_account.product_id, second_account.id, "second-task"
    )
    db_session.add_all([first_oauth, second_oauth, first_task, second_task])
    db_session.commit()

    db_session.info["workspace_id"] = first_id
    first_repo = SocialRepository(db_session)
    first_storage_key = first_repo.scoped_idempotency_key("same-client-key")
    assert first_repo.get_account(first_account.id) is not None
    assert first_repo.get_account(second_account.id) is None
    assert first_repo.get_oauth_session(first_oauth.state_digest) is not None
    assert first_repo.get_oauth_session(second_oauth.state_digest) is None
    assert first_repo.get_publish_task(first_task.id) is not None
    assert first_repo.get_publish_task(second_task.id) is None
    assert [item.id for item in first_repo.list_accounts(first_account.product_id)] == [
        first_account.id
    ]

    db_session.info["workspace_id"] = second_id
    second_repo = SocialRepository(db_session)
    second_storage_key = second_repo.scoped_idempotency_key("same-client-key")
    assert second_repo.get_account(first_account.id) is None
    assert second_repo.get_account(second_account.id) is not None
    assert second_repo.get_publish_task(first_task.id) is None
    assert second_repo.get_publish_task(second_task.id) is not None
    assert first_storage_key != second_storage_key
    assert "same-client-key" in first_storage_key
    assert "same-client-key" in second_storage_key


def test_worker_inherits_job_workspace_for_social_record_access(
    db_session: Session,
) -> None:
    first_id, _, first_account_id, second_account_id = _seed_two_workspaces(db_session)
    sessions = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    with sessions() as session:
        session.info["workspace_id"] = first_id
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=SocialIsolationProbeHandler.job_type,
                source_type="social_account",
                source_id=first_account_id,
                input_digest=hashlib.sha256(b"social-isolation").hexdigest(),
                idempotency_key="social-isolation-worker",
                input_payload={
                    "own_account_id": first_account_id,
                    "foreign_account_id": second_account_id,
                },
            )
        )

    observed: list[tuple[bool, bool]] = []
    registry = ExecutionHandlerRegistry()
    registry.register(SocialIsolationProbeHandler(sessions, observed))
    result = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="social-isolation-worker",
        lease_seconds=10,
        heartbeat_interval_seconds=0.1,
    ).run_once()

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert result.job_id == created.job.id
    assert observed == [(True, False)]
