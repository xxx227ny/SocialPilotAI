"""Advance already cost-confirmed batches without a browser being open."""

import logging
from contextlib import ExitStack

from sqlalchemy import select

from app.execution.credential_context import (
    bind_execution_api_key,
    bind_execution_provider_runtime,
    reset_execution_api_key,
    reset_execution_provider_runtime,
)
from app.execution.workspace_context import (
    bind_execution_workspace_id,
    reset_execution_workspace_id,
)
from app.models import Product, ProductVideoProductionBatch, ProductVideoProductionItem
from app.services.product_video_production_batch_service import (
    ProductVideoProductionBatchService,
)
from app.services.provider_credential_service import ProviderCredentialService

logger = logging.getLogger(__name__)


def advance_pending_production_batches(session_factory, settings) -> int:
    if not settings.enable_real_product_video:
        return 0
    with session_factory() as session:
        rows = session.execute(
            select(
                ProductVideoProductionBatch.id,
                ProductVideoProductionBatch.product_id,
                Product.workspace_id,
            )
            .join(Product)
            .where(
                ProductVideoProductionBatch.status.in_(
                    ["WAITING", "RUNNING", "PARTIAL_FAILED"]
                ),
                ProductVideoProductionBatch.cost_confirmed.is_(True),
                ProductVideoProductionBatch.items.any(
                    ProductVideoProductionItem.status.in_(["WAITING", "RUNNING"])
                ),
            )
            .order_by(ProductVideoProductionBatch.updated_at)
        ).all()
    advanced = 0
    for batch_id, product_id, workspace_id in rows:
        try:
            with session_factory() as session, ExitStack() as context:
                session.info["workspace_id"] = workspace_id
                token = bind_execution_workspace_id(workspace_id)
                context.callback(reset_execution_workspace_id, token)
                if settings.enable_user_auth:
                    if workspace_id is None:
                        continue
                    runtime = ProviderCredentialService(
                        session, settings
                    ).read_dashscope_runtime(workspace_id, require_verified=True)
                    if runtime is None:
                        continue
                    context.callback(
                        reset_execution_api_key, bind_execution_api_key(runtime.api_key)
                    )
                    context.callback(
                        reset_execution_provider_runtime,
                        bind_execution_provider_runtime(runtime),
                    )
                ProductVideoProductionBatchService(session, settings).advance(
                    product_id, batch_id
                )
                advanced += 1
        except Exception:
            # Never log provider credentials or exception payloads. A failing
            # batch must not prevent other workspaces or the worker from running.
            logger.warning("Production batch %s could not advance", batch_id)
    return advanced
