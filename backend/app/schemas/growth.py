import hashlib
import json
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.campaign import CampaignMetricsSchema

SUPPORTED_GROWTH_PLATFORMS = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "pinterest": "Pinterest",
}
GROWTH_RECOMMENDATION_CONTRACT_VERSION = "growth-recommendation-v1"
BoundedText = Annotated[str, Field(min_length=1, max_length=400)]
ShortText = Annotated[str, Field(min_length=1, max_length=160)]


class StrictGrowthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GrowthRecommendation(BaseModel):
    """Frozen Presentation recommendation contract."""

    problems: list[str] = Field(min_length=1)
    recommendations: list[str] = Field(min_length=1)
    budget_suggestion: str = Field(min_length=1)
    creative_suggestions: list[str] = Field(min_length=1)

    @field_validator("budget_suggestion")
    @classmethod
    def validate_budget_suggestion(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("budget_suggestion cannot be empty")
        return cleaned

    @field_validator("problems", "recommendations", "creative_suggestions")
    @classmethod
    def validate_non_empty_lists(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("growth recommendation lists cannot contain empty values")
        return cleaned


def normalize_growth_platform(value: str) -> str:
    canonical = SUPPORTED_GROWTH_PLATFORMS.get(value.strip().casefold())
    if canonical is None:
        raise ValueError("unsupported growth recommendation platform")
    return canonical


class GrowthObservation(StrictGrowthModel):
    scope: Literal["overall", "platform"]
    platform: str | None = Field(default=None, max_length=50)
    metric: Literal["ctr", "conversion_rate", "cpa", "roas"]
    direction: Literal["improve", "test", "protect", "investigate"]
    hypothesis: BoundedText

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str | None) -> str | None:
        return None if value is None else normalize_growth_platform(value)

    @model_validator(mode="after")
    def validate_scope_platform(self) -> "GrowthObservation":
        if self.scope == "overall" and self.platform is not None:
            raise ValueError("overall observations cannot specify a platform")
        if self.scope == "platform" and self.platform is None:
            raise ValueError("platform observations require a platform")
        return self


class GrowthCopyConstraint(StrictGrowthModel):
    platform: str
    hook_direction: BoundedText
    message_angle: BoundedText
    cta_direction: BoundedText
    must_preserve: list[ShortText] = Field(min_length=1, max_length=6)
    must_avoid: list[ShortText] = Field(min_length=1, max_length=6)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        return normalize_growth_platform(value)


class GrowthVideoConstraint(StrictGrowthModel):
    platform: str
    opening_hook_direction: BoundedText
    visual_focus: BoundedText
    pacing_direction: BoundedText
    cta_direction: BoundedText
    must_preserve: list[ShortText] = Field(min_length=1, max_length=6)
    must_avoid: list[ShortText] = Field(min_length=1, max_length=6)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        return normalize_growth_platform(value)


class GrowthRecommendationConstraints(StrictGrowthModel):
    summary: BoundedText
    observations: list[GrowthObservation] = Field(min_length=1, max_length=8)
    copy_constraints: list[GrowthCopyConstraint] = Field(min_length=1, max_length=4)
    video_constraint: GrowthVideoConstraint
    budget_guidance: BoundedText

    @model_validator(mode="after")
    def validate_unique_copy_platforms(
        self,
    ) -> "GrowthRecommendationConstraints":
        platforms = [item.platform for item in self.copy_constraints]
        if len({item.casefold() for item in platforms}) != len(platforms):
            raise ValueError("copy constraint platforms must be unique")
        return self


class GrowthAnalysisRequest(StrictGrowthModel):
    expected_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class GrowthRecommendationPreflightRead(StrictGrowthModel):
    product_id: int
    context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    marketing_strategy_id: int | None
    copy_matrix_id: int | None
    video_project_id: int | None
    input_ready: bool
    provider_configured: bool
    execution_enabled: bool
    contract_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    provider_label: str
    model_label: str
    preflight_only: Literal[True] = True
    execution_will_call_ai: Literal[True] = True
    execution_will_write_database: Literal[False] = False
    execution_will_generate_copy: Literal[False] = False
    execution_will_generate_video: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    cost_notice: str
    attribution_notice: str


class GrowthAnalysisResponse(StrictGrowthModel):
    version: Literal["v1"] = "v1"
    product_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int
    source_copy_matrix_id: int
    source_video_project_id: int
    recommendation: GrowthRecommendationConstraints
    recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommendation_integrity_scope: Literal[
        "deterministic_round_trip_not_authenticated"
    ] = "deterministic_round_trip_not_authenticated"
    recommendation_only: Literal[True] = True
    recommendation_persisted: Literal[False] = False
    campaign_association_scope: Literal["product_only"] = "product_only"
    causal_attribution_allowed: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    budget_change_allowed: Literal[False] = False
    copy_generation_triggered: Literal[False] = False
    video_generation_triggered: Literal[False] = False
    provider_calls: Literal[1] = 1


class GrowthOptimizationPolicy(StrictGrowthModel):
    total_budget: float = Field(gt=0, le=1_000_000_000)
    target_roas: float = Field(gt=0, le=1000)
    minimum_platform_share: float = Field(default=0.05, ge=0, le=0.25)
    performance_tilt_share: float = Field(default=0.15, ge=0, le=0.25)
    maximum_bid_adjustment_pct: float = Field(default=0.2, ge=0, le=0.5)


class GrowthOptimizationPlanRequest(StrictGrowthModel):
    analysis: GrowthAnalysisResponse
    policy: GrowthOptimizationPolicy


class GrowthPlatformOptimizationAction(StrictGrowthModel):
    platform: str
    observed_roas: float | None
    current_spend: float = Field(ge=0)
    current_share: float = Field(ge=0, le=1)
    recommended_budget: float = Field(ge=0)
    recommended_share: float = Field(ge=0, le=1)
    budget_change: float
    budget_change_pct: float | None
    bid_adjustment_pct: float = Field(ge=-0.5, le=0.5)
    action: Literal["increase", "decrease", "hold"]


class GrowthOptimizationPlanRead(StrictGrowthModel):
    version: Literal["v1"] = "v1"
    product_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: GrowthOptimizationPolicy
    current_total_spend: float = Field(ge=0)
    recommended_total_budget: float = Field(gt=0)
    actions: list[GrowthPlatformOptimizationAction] = Field(min_length=1)
    exact_source_validated: Literal[True] = True
    requires_qwen_recommendation: Literal[True] = True
    automatic_plan_generated: Literal[True] = True
    simulation_only: Literal[True] = True
    plan_persisted: Literal[False] = False
    external_execution_allowed: Literal[False] = False
    provider_calls: Literal[0] = 0


class GrowthOptimizationRunCreateRequest(GrowthOptimizationPlanRequest):
    idempotency_key: str = Field(min_length=8, max_length=160)
    activate_internal: bool = True
    source_automation_cycle_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_activation_for_replan_resolution(
        self,
    ) -> "GrowthOptimizationRunCreateRequest":
        if self.source_automation_cycle_id is not None and not self.activate_internal:
            raise ValueError("a replan resolution must activate the new internal plan")
        return self


class GrowthOptimizationRunRead(StrictGrowthModel):
    id: int
    product_id: int
    idempotency_key: str
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: GrowthOptimizationPolicy
    actions: list[GrowthPlatformOptimizationAction] = Field(min_length=1)
    current_total_spend: float = Field(ge=0)
    recommended_total_budget: float = Field(gt=0)
    status: Literal["PROPOSED", "ACTIVE", "SUPERSEDED"]
    execution_scope: Literal["INTERNAL_PLAN_ONLY"]
    external_execution_status: Literal["NOT_CONNECTED"]
    created_at: datetime
    activated_at: datetime | None
    requires_qwen_recommendation: Literal[True] = True
    external_execution_allowed: Literal[False] = False


class GrowthOptimizationRunCreateRead(StrictGrowthModel):
    run: GrowthOptimizationRunRead
    reused: bool
    automatic_internal_application: bool
    provider_calls: Literal[0] = 0


class GrowthOptimizationRunActivateRead(StrictGrowthModel):
    run: GrowthOptimizationRunRead
    reused: bool
    external_execution_allowed: Literal[False] = False
    provider_calls: Literal[0] = 0


class GrowthOptimizationExecutionPreflightRead(StrictGrowthModel):
    product_id: int
    optimization_run_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ready: Literal[True] = True
    execution_mode: Literal["SANDBOX"] = "SANDBOX"
    provider_name: Literal["sandbox_ad_adapter"] = "sandbox_ad_adapter"
    requires_explicit_confirmation: Literal[True] = True
    external_mutation_allowed: Literal[False] = False
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class GrowthOptimizationExecutionRequest(StrictGrowthModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    expected_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_sandbox_execution: Literal[True]


class GrowthOptimizationExecutionRead(StrictGrowthModel):
    id: int
    product_id: int
    optimization_run_id: int
    idempotency_key: str
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_actions: list[GrowthPlatformOptimizationAction] = Field(min_length=1)
    target_actions: list[GrowthPlatformOptimizationAction] = Field(min_length=1)
    result_actions: list[GrowthPlatformOptimizationAction] = Field(min_length=1)
    status: Literal["SUCCEEDED", "ROLLED_BACK"]
    execution_mode: Literal["SANDBOX"]
    provider_name: Literal["sandbox_ad_adapter"]
    external_mutation_performed: Literal[False]
    created_at: datetime
    rolled_back_at: datetime | None
    trigger_kind: Literal["MANUAL_CONFIRMATION", "AUTO_POLICY"]


class GrowthOptimizationExecutionResult(StrictGrowthModel):
    execution: GrowthOptimizationExecutionRead
    reused: bool
    external_mutation_performed: Literal[False] = False
    provider_calls: Literal[0] = 0


class GrowthAutomationControlUpdate(StrictGrowthModel):
    mode: Literal["MANUAL", "AUTO_SANDBOX"]
    kill_switch_engaged: bool
    maximum_total_budget: float = Field(gt=0, le=1_000_000_000)
    maximum_budget_change_pct: float = Field(ge=0, le=0.5)
    maximum_bid_adjustment_pct: float = Field(ge=0, le=0.5)
    monitoring_enabled: bool = False
    evaluation_interval_seconds: int = Field(default=900, ge=60, le=86400)
    confirm_auto_sandbox: bool = False

    @model_validator(mode="after")
    def require_confirmation_when_armed(self) -> "GrowthAutomationControlUpdate":
        if (
            self.mode == "AUTO_SANDBOX"
            and not self.kill_switch_engaged
            and not self.confirm_auto_sandbox
        ):
            raise ValueError("arming AUTO_SANDBOX requires explicit confirmation")
        return self


class GrowthAutomationControlRead(StrictGrowthModel):
    product_id: int
    mode: Literal["MANUAL", "AUTO_SANDBOX"]
    kill_switch_engaged: bool
    maximum_total_budget: float
    maximum_budget_change_pct: float
    maximum_bid_adjustment_pct: float
    monitoring_enabled: bool
    evaluation_interval_seconds: int
    next_evaluation_at: datetime | None
    last_execution_id: int | None
    last_evaluated_at: datetime | None
    updated_at: datetime | None
    persisted: bool
    execution_mode: Literal["SANDBOX"] = "SANDBOX"
    provider_name: Literal["sandbox_ad_adapter"] = "sandbox_ad_adapter"
    external_mutation_allowed: Literal[False] = False


class GrowthAutomationEvaluationRequest(StrictGrowthModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    expected_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class GrowthAutomationCycleRequest(StrictGrowthModel):
    force: bool = False


class GrowthAutomationCycleRead(StrictGrowthModel):
    id: int
    product_id: int
    optimization_run_id: int | None
    execution_id: int | None
    cycle_key: str
    context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal[
        "EXECUTED",
        "NO_CHANGE",
        "REPLAN_REQUIRED",
        "KILL_SWITCHED",
        "MANUAL_REVIEW_REQUIRED",
        "NO_ACTIVE_PLAN",
    ]
    observed_at: datetime
    next_evaluation_at: datetime
    execution_mode: Literal["SANDBOX"]
    external_mutation_performed: Literal[False]
    resolved_by_optimization_run_id: int | None
    resolved_at: datetime | None
    resolution_status: Literal["UNRESOLVED", "RESOLVED"]
    provider_calls: Literal[0] = 0


class GrowthAutomationCycleResult(StrictGrowthModel):
    cycle: GrowthAutomationCycleRead | None
    due: bool
    reused: bool = False
    provider_calls: Literal[0] = 0
    external_mutation_performed: Literal[False] = False


def compute_recommendation_digest(
    *,
    product_id: int,
    source_context_digest: str,
    source_marketing_strategy_id: int,
    source_copy_matrix_id: int,
    source_video_project_id: int,
    recommendation: GrowthRecommendationConstraints,
) -> str:
    """Bind one strict Recommendation to its exact authoritative source."""
    payload = {
        "contract_version": GROWTH_RECOMMENDATION_CONTRACT_VERSION,
        "product_id": product_id,
        "source_context_digest": source_context_digest,
        "source_marketing_strategy_id": source_marketing_strategy_id,
        "source_copy_matrix_id": source_copy_matrix_id,
        "source_video_project_id": source_video_project_id,
        "recommendation": recommendation.model_dump(mode="json"),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class FeedbackPlatformMetrics(BaseModel):
    platform: str
    metrics: CampaignMetricsSchema


class FeedbackContextRead(BaseModel):
    version: Literal["v1"] = "v1"
    product_id: int
    data_source: Literal["stored_campaigns"] = "stored_campaigns"
    context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    feedback_only: Literal[True] = True
    recommendation_generated: Literal[False] = False
    generation_triggered: Literal[False] = False
    provider_calls: Literal[0] = 0

    campaign_ids: list[int]
    campaign_count: int = Field(ge=0)
    date_from: date | None
    date_to: date | None
    platforms: list[str]
    overall_metrics: CampaignMetricsSchema | None
    platform_metrics: list[FeedbackPlatformMetrics]

    marketing_strategy_id: int | None
    copy_matrix_id: int | None
    video_project_id: int | None
    content_chain_ready: bool
    content_chain_selection: Literal["latest_video_project_exact_chain"] = (
        "latest_video_project_exact_chain"
    )

    campaign_association_scope: Literal["product_only"] = "product_only"
    creative_attribution_persisted: Literal[False] = False
    marketing_brief_attribution_persisted: Literal[False] = False
    association_notice: str

    context_ready: bool
    metrics_ready: bool
    missing_requirements: list[str]
