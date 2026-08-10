from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.models import MarketingBrief, Product
from app.providers import TextGenerationProvider
from app.services.marketing_strategy_service import MarketingStrategyService
from app.services.strategy_preflight import StrategyPreflightService

QWEN_STRATEGY_GENERATE_V1 = "qwen.strategy.generate.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class QwenStrategyGenerateV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    marketing_brief_id: int = Field(gt=0)
    preflight_product_id: int = Field(gt=0)
    preflight_marketing_brief_id: int = Field(gt=0)
    frozen_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ContextTextProvider(TextGenerationProvider):
    def __init__(
        self, context: ExecutionContext, provider: TextGenerationProvider
    ) -> None:
        self.context = context
        self.provider = provider

    def generate(self, prompt: str) -> str:
        self.context.before_provider_call(may_submit_external=True)
        return self.provider.generate(prompt)


class QwenStrategyGenerateV1Handler:
    job_type = QWEN_STRATEGY_GENERATE_V1
    input_schema = QwenStrategyGenerateV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: TextGenerationProvider,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings

    def execute(
        self, context: ExecutionContext, payload: BaseModel
    ) -> HandlerResult:
        data = QwenStrategyGenerateV1Input.model_validate(payload)
        if (
            data.product_id != data.preflight_product_id
            or data.marketing_brief_id != data.preflight_marketing_brief_id
        ):
            return HandlerResult.failed("STRATEGY_PREFLIGHT_IDENTITY_MISMATCH")

        with self.session_factory() as session:
            product = session.get(Product, data.product_id)
            brief = session.get(MarketingBrief, data.marketing_brief_id)
            if product is None or brief is None:
                return HandlerResult.failed("STRATEGY_SOURCE_NOT_FOUND")
            if brief.product_id != product.id:
                return HandlerResult.failed("STRATEGY_SOURCE_RELATIONSHIP_INVALID")
            try:
                preflight = StrategyPreflightService(
                    session, self.settings
                ).run(brief.id)
            except AppError:
                return HandlerResult.failed("STRATEGY_PREFLIGHT_FAILED")
            if (
                preflight.product_id != data.product_id
                or preflight.task_id != data.marketing_brief_id
            ):
                return HandlerResult.failed("STRATEGY_PREFLIGHT_IDENTITY_MISMATCH")
            if preflight.input_digest != data.frozen_digest:
                return HandlerResult.failed("STRATEGY_FROZEN_DIGEST_MISMATCH")
            if not preflight.ready_for_execution:
                return HandlerResult.failed("STRATEGY_PREFLIGHT_NOT_READY")

            guarded_provider = _ContextTextProvider(context, self.provider)
            try:
                result = MarketingStrategyService(
                    session, guarded_provider, self.settings
                ).generate_for_marketing_task(brief.id)
            except AppError:
                if context.provider_state()[1]:
                    raise
                return HandlerResult.failed("STRATEGY_EXECUTION_REJECTED")
            return HandlerResult.succeeded(
                provider_name="qwen",
                result_entity_type="marketing_strategy",
                result_entity_id=result.strategy.id,
            )
