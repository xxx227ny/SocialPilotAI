from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, VideoScriptVersion
from app.services.video_script_preflight import _model_payload, stable_digest


@dataclass(frozen=True)
class VideoScriptSourceIdentity:
    strategy: MarketingStrategy
    copy_matrix: CopyMatrix | None


def validate_video_script_source_identity(
    session: Session,
    version: VideoScriptVersion,
    *,
    product_id: int,
    platform: str,
) -> VideoScriptSourceIdentity:
    """Validate the immutable Strategy/Copy chain before any paid media call."""
    if version.strategy_id is None or version.strategy_digest is None:
        raise AppError("ScriptVersion lacks exact Strategy identity", 409)
    strategy = session.get(MarketingStrategy, version.strategy_id)
    if strategy is None or strategy.product_id != product_id:
        raise AppError("Frozen ScriptVersion Strategy identity changed", 409)
    strategy_digest = stable_digest(
        _model_payload(
            strategy,
            (
                "id",
                "product_id",
                "positioning",
                "audience_insights",
                "angles",
                "risks",
                "evidence",
            ),
        )
    )
    if strategy_digest != version.strategy_digest:
        raise AppError("Frozen ScriptVersion Strategy identity changed", 409)

    if version.copy_matrix_id is None:
        if version.target_platform_copy_digest is not None:
            raise AppError("Frozen ScriptVersion Copy identity is inconsistent", 409)
        return VideoScriptSourceIdentity(strategy=strategy, copy_matrix=None)

    copy_matrix = session.get(CopyMatrix, version.copy_matrix_id)
    if (
        copy_matrix is None
        or copy_matrix.product_id != product_id
        or copy_matrix.marketing_strategy_id != strategy.id
        or version.target_platform_copy_digest is None
    ):
        raise AppError("Frozen ScriptVersion Copy identity changed", 409)
    target_copy = next(
        (
            item
            for item in copy_matrix.copies
            if str(item.get("platform", "")).casefold() == platform.casefold()
        ),
        None,
    )
    if (
        target_copy is None
        or stable_digest(target_copy) != version.target_platform_copy_digest
    ):
        raise AppError("Frozen ScriptVersion Copy identity changed", 409)
    return VideoScriptSourceIdentity(strategy=strategy, copy_matrix=copy_matrix)
