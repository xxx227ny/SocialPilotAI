import json
from datetime import UTC, datetime, timedelta
from threading import Lock

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.providers import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.repositories.copy import CopyMatrixRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.repositories.video import VideoProjectRepository
from app.schemas.video import (
    InitialVideoProjectExecutionRead,
    InitialVideoProjectExecutionRequest,
    InitialVideoProjectSourceRequest,
    V2VideoProjectProviderOutput,
    VideoPlanSchema,
    VideoProjectSchema,
)
from app.services.content_studio_service import ContentStudioService
from app.services.initial_video_project_preflight import (
    INITIAL_VIDEO_PROJECT_ASSOCIATION_NOTICE,
    INITIAL_VIDEO_PROJECT_PREFLIGHT_TTL,
    InitialVideoProjectPreflightService,
)

_INITIAL_VIDEO_PROJECT_LOCK = Lock()
_EXPIRY_CLOCK_SKEW = timedelta(seconds=5)


class InitialVideoProjectGenerationService:
    """Create or reuse one exact first VideoProject without implicit recovery."""

    def __init__(
        self,
        session: Session,
        provider: TextGenerationProvider,
        settings: Settings,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings
        self.product_repository = ProductRepository(session)
        self.strategy_repository = MarketingStrategyRepository(session)
        self.copy_repository = CopyMatrixRepository(session)
        self.video_repository = VideoProjectRepository(session)

    def generate(
        self,
        product_id: int,
        data: InitialVideoProjectExecutionRequest,
    ) -> InitialVideoProjectExecutionRead:
        self._require_execution_enabled()
        source = InitialVideoProjectSourceRequest.model_validate(
            data.model_dump(
                include={
                    "strategy_id",
                    "copy_matrix_id",
                    "platform",
                    "duration_seconds",
                    "aspect_ratio",
                }
            )
        )
        self._require_valid_expiry(data.preflight_expires_at)
        preflight = InitialVideoProjectPreflightService(
            self.session, self.settings
        ).run(
            product_id,
            source,
            expires_at=data.preflight_expires_at,
        )
        if not preflight.ready_for_execution:
            raise AppError(
                "Initial VideoProject inputs changed or execution is not ready; "
                "run Preflight again",
                status_code=409,
            )
        if preflight.preflight_digest != data.expected_preflight_digest:
            raise AppError(
                "Initial VideoProject Preflight changed; run Preflight again",
                status_code=409,
            )

        with _INITIAL_VIDEO_PROJECT_LOCK:
            self._require_valid_expiry(data.preflight_expires_at)
            locked_preflight = InitialVideoProjectPreflightService(
                self.session, self.settings
            ).run(
                product_id,
                source,
                expires_at=data.preflight_expires_at,
            )
            if (
                not locked_preflight.ready_for_execution
                or locked_preflight.preflight_digest
                != data.expected_preflight_digest
            ):
                raise AppError(
                    "Initial VideoProject source changed; run Preflight again",
                    status_code=409,
                )
            existing = self.video_repository.get_by_initial_identity(
                product_id=product_id,
                marketing_strategy_id=data.strategy_id,
                copy_matrix_id=data.copy_matrix_id,
                platform=data.platform,
                duration_seconds=data.duration_seconds,
                aspect_ratio=data.aspect_ratio,
            )
            if existing is not None:
                return self._response(
                    project=existing,
                    preflight_digest=data.expected_preflight_digest,
                    reused=True,
                    provider_calls=0,
                )

            product = self.product_repository.get(product_id)
            strategy = self.strategy_repository.get(data.strategy_id)
            copy_matrix = self.copy_repository.get(data.copy_matrix_id)
            if product is None or strategy is None or copy_matrix is None:
                raise AppError(
                    "Initial VideoProject source changed; run Preflight again",
                    status_code=409,
                )
            raw_result = self._call_provider(
                ContentStudioService._build_prompt(
                    product,
                    strategy,
                    copy_matrix,
                    source,
                )
            )
            try:
                provider_output = V2VideoProjectProviderOutput.model_validate_json(
                    raw_result,
                    context={"duration_seconds": data.duration_seconds},
                )
                plan = VideoPlanSchema.model_validate(
                    {
                        **provider_output.model_dump(mode="json"),
                        "platform": data.platform,
                        "duration_seconds": data.duration_seconds,
                        "aspect_ratio": data.aspect_ratio,
                    }
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise AppError(
                    "Qwen returned invalid initial VideoProject data",
                    status_code=502,
                ) from exc
            try:
                project = self.video_repository.create_for_exact_chain(
                    product_id=product.id,
                    marketing_strategy_id=strategy.id,
                    copy_matrix_id=copy_matrix.id,
                    plan=plan,
                )
            except Exception as exc:
                raise AppError(
                    "Initial VideoProject could not be saved",
                    status_code=500,
                ) from exc
            return self._response(
                project=project,
                preflight_digest=data.expected_preflight_digest,
                reused=False,
                provider_calls=1,
            )

    def _require_execution_enabled(self) -> None:
        if not self.settings.enable_video_project_execution:
            raise AppError(
                "VideoProject execution is disabled by the server",
                status_code=503,
            )

    @staticmethod
    def _require_valid_expiry(expires_at: datetime) -> None:
        if expires_at.tzinfo is None:
            raise AppError("Initial VideoProject Preflight expiry is invalid", 409)
        now = datetime.now(UTC)
        normalized = expires_at.astimezone(UTC)
        if normalized <= now or normalized > (
            now + INITIAL_VIDEO_PROJECT_PREFLIGHT_TTL + _EXPIRY_CLOCK_SKEW
        ):
            raise AppError(
                "Initial VideoProject Preflight expired; run Preflight again",
                status_code=409,
            )

    def _call_provider(self, prompt: str) -> str:
        try:
            return self.provider.generate(prompt)
        except ProviderAuthenticationError as exc:
            raise AppError("Qwen authentication failed", status_code=502) from exc
        except ProviderConnectionError as exc:
            raise AppError("Qwen service is unavailable", status_code=503) from exc
        except ProviderQuotaError as exc:
            raise AppError(
                "Qwen quota or rate limit prevents execution",
                status_code=503,
            ) from exc
        except ProviderModelError as exc:
            raise AppError("Qwen generation failed", status_code=502) from exc

    @staticmethod
    def _response(
        *,
        project: object,
        preflight_digest: str,
        reused: bool,
        provider_calls: int,
    ) -> InitialVideoProjectExecutionRead:
        return InitialVideoProjectExecutionRead(
            product_id=project.product_id,
            strategy_id=project.marketing_strategy_id,
            copy_matrix_id=project.copy_matrix_id,
            preflight_digest=preflight_digest,
            generated_video_project=VideoProjectSchema.model_validate(project),
            reused=reused,
            provider_calls=provider_calls,
            association_notice=INITIAL_VIDEO_PROJECT_ASSOCIATION_NOTICE,
        )
