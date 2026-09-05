import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.provider_runtime import resolve_workspace_provider_runtime
from app.execution.credential_context import (
    current_execution_api_key,
    current_execution_provider_runtime,
    execution_api_key_is_bound,
)
from app.execution.production_scheduler import advance_pending_production_batches
from app.execution.workspace_context import current_execution_workspace_id
from app.main import app
from app.models import ExecutionJob, Product, ProductVideoProductionBatch, Workspace
from app.services.product_video_production_batch_service import (
    ProductVideoProductionBatchService,
)
from app.services.provider_credential_service import ProviderCredentialService
from app.services.wanx_product_image_service import WanxProductImageService
from tests.test_product_video_production_batches import (
    _settings,
)
from tests.test_product_video_production_batches import (
    test_create_persistent_single_platform_batch as create_batch,
)


def test_background_tick_enqueues_without_browser(client, db_session, tmp_path):
    create_batch(client, db_session, tmp_path)
    settings = _settings(tmp_path)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    assert db_session.query(ExecutionJob).count() == 0
    assert advance_pending_production_batches(factory, settings) == 1
    db_session.expire_all()
    assert db_session.query(ExecutionJob).count() == 2
    batch = db_session.query(ProductVideoProductionBatch).one()
    assert batch.items[0].stage == "GENERATING_IMAGES"
    # Another tick waits for existing jobs, rather than enqueueing duplicates.
    assert advance_pending_production_batches(factory, settings) == 1
    assert db_session.query(ExecutionJob).count() == 2


@pytest.mark.parametrize("status", ["PAUSED", "FAILED", "CANCELLED", "SUCCEEDED"])
def test_background_tick_never_retries_terminal_or_paused(
    client, db_session, tmp_path, status
):
    create_batch(client, db_session, tmp_path)
    batch = db_session.query(ProductVideoProductionBatch).one()
    batch.status = status
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind())
    assert advance_pending_production_batches(factory, _settings(tmp_path)) == 0
    assert db_session.query(ExecutionJob).count() == 0


def test_background_requires_consent_and_workspace_credential(
    client, db_session, tmp_path
):
    create_batch(client, db_session, tmp_path)
    batch = db_session.query(ProductVideoProductionBatch).one()
    batch.cost_confirmed = False
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind())
    settings = _settings(tmp_path)
    assert advance_pending_production_batches(factory, settings) == 0
    batch.cost_confirmed = True
    db_session.commit()
    settings.enable_user_auth = True
    assert advance_pending_production_batches(factory, settings) == 0
    assert db_session.query(ExecutionJob).count() == 0
    app.dependency_overrides.pop(get_settings, None)


def test_recovery_rolls_back_all_replacements_on_enqueue_error(
    client, db_session, tmp_path, monkeypatch
):
    create_batch(client, db_session, tmp_path)
    batch = db_session.query(ProductVideoProductionBatch).one()
    service = ProductVideoProductionBatchService(db_session, _settings(tmp_path))
    service.advance(batch.product_id, batch.id)
    for job in db_session.query(ExecutionJob).all():
        job.status = "FAILED"
    db_session.commit()
    service.advance(batch.product_id, batch.id)
    original = WanxProductImageService.enqueue
    calls = []

    def fail_second(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("isolated enqueue failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(WanxProductImageService, "enqueue", fail_second)
    with pytest.raises(RuntimeError, match="isolated enqueue failure"):
        service.resume(batch.product_id, batch.id, retry_failed_images=True)
    assert len(calls) == 2
    assert db_session.query(ExecutionJob).count() == 2
    assert db_session.get(ProductVideoProductionBatch, batch.id).status == "FAILED"


def test_scheduler_binds_and_clears_exact_workspace_runtime(
    client, db_session, tmp_path, monkeypatch
):
    create_batch(client, db_session, tmp_path)
    workspace = Workspace(name="Isolated scheduler workspace")
    db_session.add(workspace)
    db_session.flush()
    product = db_session.query(Product).one()
    product.workspace_id = workspace.id
    db_session.commit()
    workspace_id = workspace.id
    runtime = resolve_workspace_provider_runtime(
        api_key="isolated-not-real",
        region="cn-beijing",
        provider_workspace_id="test-workspace",
    )

    def resolve(self, requested_id, *, require_verified):
        assert requested_id == workspace_id
        assert require_verified
        return runtime

    calls = []

    def advance(self, product_id, batch_id):
        assert self.session.info["workspace_id"] == workspace_id
        assert current_execution_workspace_id() == workspace_id
        assert current_execution_api_key() == runtime.api_key
        assert current_execution_provider_runtime() == runtime
        calls.append(batch_id)

    monkeypatch.setattr(ProviderCredentialService, "read_dashscope_runtime", resolve)
    monkeypatch.setattr(ProductVideoProductionBatchService, "advance", advance)
    settings = _settings(tmp_path)
    settings.enable_user_auth = True
    settings.user_credential_encryption_key = None
    # Credential service constructor normally validates its encryption key.
    monkeypatch.setattr(ProviderCredentialService, "__init__", lambda *args: None)
    factory = sessionmaker(bind=db_session.get_bind())
    assert advance_pending_production_batches(factory, settings) == 1
    assert len(calls) == 1
    assert current_execution_workspace_id() is None
    assert not execution_api_key_is_bound()


def test_partial_failure_continues_other_active_platforms(client, db_session, tmp_path):
    create_batch(client, db_session, tmp_path)
    batch = db_session.query(ProductVideoProductionBatch).one()
    batch.status = "PARTIAL_FAILED"
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind())
    assert advance_pending_production_batches(factory, _settings(tmp_path)) == 1
    assert db_session.query(ExecutionJob).count() == 2
