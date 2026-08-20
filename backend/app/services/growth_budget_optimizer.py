from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.schemas.growth import (
    GrowthOptimizationPlanRead,
    GrowthOptimizationPlanRequest,
    GrowthPlatformOptimizationAction,
    compute_recommendation_digest,
)
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_recommendation_preflight import supported_growth_platform


class GrowthBudgetOptimizer:
    """Build a deterministic, non-persistent plan from one Qwen analysis."""

    def __init__(self, session: Session) -> None:
        self.feedback_service = FeedbackContextService(session)

    def plan(
        self,
        product_id: int,
        request: GrowthOptimizationPlanRequest,
    ) -> GrowthOptimizationPlanRead:
        context, strategy, copy_matrix, video_project = (
            self.feedback_service.get_with_validated_chain(product_id)
        )
        analysis = request.analysis
        if (
            not context.context_ready
            or strategy is None
            or copy_matrix is None
            or video_project is None
        ):
            raise AppError(
                "FeedbackContext is not ready; generate a new analysis first",
                status_code=409,
            )
        if analysis.product_id != product_id:
            raise AppError("Growth analysis was not found", status_code=404)
        if analysis.source_context_digest != context.context_digest:
            raise AppError(
                "FeedbackContext changed; generate a new analysis first",
                status_code=409,
            )
        if (
            analysis.source_marketing_strategy_id != strategy.id
            or analysis.source_copy_matrix_id != copy_matrix.id
            or analysis.source_video_project_id != video_project.id
        ):
            raise AppError(
                "Growth analysis source chain changed; generate a new analysis first",
                status_code=409,
            )
        expected_digest = compute_recommendation_digest(
            product_id=product_id,
            source_context_digest=context.context_digest,
            source_marketing_strategy_id=strategy.id,
            source_copy_matrix_id=copy_matrix.id,
            source_video_project_id=video_project.id,
            recommendation=analysis.recommendation,
        )
        if analysis.recommendation_digest != expected_digest:
            raise AppError(
                "Growth recommendation changed; generate a new analysis first",
                status_code=409,
            )

        metrics_by_platform = {}
        for item in context.platform_metrics:
            platform = supported_growth_platform(item.platform)
            if platform is None:
                continue
            if platform in metrics_by_platform:
                raise AppError(
                    "Campaign platforms are ambiguous; normalize the source data",
                    status_code=409,
                )
            metrics_by_platform[platform] = item.metrics
        if not metrics_by_platform:
            raise AppError(
                "No supported campaign metrics are available",
                status_code=409,
            )
        policy = request.policy
        platform_count = len(metrics_by_platform)
        if policy.minimum_platform_share * platform_count > 1:
            raise AppError(
                "Minimum platform shares exceed the available budget",
                status_code=422,
            )

        platforms = sorted(metrics_by_platform)
        current_total = sum(
            (Decimal(str(metrics_by_platform[item].spend)) for item in platforms),
            Decimal("0"),
        )
        if current_total:
            current_shares = {
                item: Decimal(str(metrics_by_platform[item].spend)) / current_total
                for item in platforms
            }
        else:
            equal_share = Decimal("1") / Decimal(platform_count)
            current_shares = {item: equal_share for item in platforms}

        target_roas = Decimal(str(policy.target_roas))
        tilt = Decimal(str(policy.performance_tilt_share))
        floor = Decimal(str(policy.minimum_platform_share))
        tilted: dict[str, Decimal] = {}
        for platform in platforms:
            observed = metrics_by_platform[platform].roas
            ratio = Decimal(str(observed or 0)) / target_roas
            performance = max(Decimal("-1"), min(Decimal("1"), ratio - 1))
            tilted[platform] = max(
                Decimal("0"), current_shares[platform] + performance * tilt
            )
        shares = self._apply_floor(tilted, floor)
        budgets = self._allocate_cents(
            Decimal(str(policy.total_budget)), shares, platforms
        )

        actions = []
        bid_cap = Decimal(str(policy.maximum_bid_adjustment_pct))
        for platform in platforms:
            metrics = metrics_by_platform[platform]
            current_spend = Decimal(str(metrics.spend))
            recommended = budgets[platform]
            change = recommended - current_spend
            change_pct = change / current_spend if current_spend else None
            observed_ratio = Decimal(str(metrics.roas or 0)) / target_roas
            bid_change = max(
                -bid_cap,
                min(bid_cap, (observed_ratio - 1) * Decimal("0.2")),
            )
            action = (
                "increase"
                if bid_change > Decimal("0.005")
                else "decrease"
                if bid_change < Decimal("-0.005")
                else "hold"
            )
            actions.append(
                GrowthPlatformOptimizationAction(
                    platform=platform,
                    observed_roas=metrics.roas,
                    current_spend=float(current_spend),
                    current_share=float(current_shares[platform]),
                    recommended_budget=float(recommended),
                    recommended_share=float(shares[platform]),
                    budget_change=float(change),
                    budget_change_pct=(
                        round(float(change_pct), 6) if change_pct is not None else None
                    ),
                    bid_adjustment_pct=round(float(bid_change), 6),
                    action=action,
                )
            )
        return GrowthOptimizationPlanRead(
            product_id=product_id,
            source_context_digest=context.context_digest,
            source_recommendation_digest=expected_digest,
            policy=policy,
            current_total_spend=float(current_total),
            recommended_total_budget=round(policy.total_budget, 2),
            actions=actions,
        )

    @staticmethod
    def _apply_floor(tilted: dict[str, Decimal], floor: Decimal) -> dict[str, Decimal]:
        count = Decimal(len(tilted))
        available = Decimal("1") - floor * count
        weights = {
            key: max(value - floor, Decimal("0")) for key, value in tilted.items()
        }
        weight_total = sum(weights.values(), Decimal("0"))
        if not weight_total:
            equal = Decimal("1") / count
            return {key: equal for key in tilted}
        return {key: floor + available * weights[key] / weight_total for key in tilted}

    @staticmethod
    def _allocate_cents(
        total_budget: Decimal,
        shares: dict[str, Decimal],
        platforms: list[str],
    ) -> dict[str, Decimal]:
        total_cents = int(
            (total_budget * 100).quantize(Decimal("1"), rounding=ROUND_DOWN)
        )
        raw = {platform: shares[platform] * total_cents for platform in platforms}
        cents = {
            platform: int(raw[platform].to_integral_value(rounding=ROUND_DOWN))
            for platform in platforms
        }
        remainder = total_cents - sum(cents.values())
        order = sorted(
            platforms,
            key=lambda platform: (-(raw[platform] - cents[platform]), platform),
        )
        for platform in order[:remainder]:
            cents[platform] += 1
        return {platform: Decimal(cents[platform]) / 100 for platform in platforms}
