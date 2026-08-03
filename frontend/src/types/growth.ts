export interface CampaignUploadResponse {
  product_id: number;
  imported_count: number;
}

export type ProviderFailurePhase =
  | "connect"
  | "request"
  | "response"
  | "schema"
  | "delivery";

export type ProviderSafeErrorCode =
  | "connection_failed"
  | "dns_resolution_failed"
  | "tcp_connection_refused"
  | "connect_timeout"
  | "network_unreachable"
  | "tls_handshake_failed"
  | "tls_certificate_failed"
  | "connection_reset_before_request"
  | "connection_failed_unknown"
  | "proxy_unavailable"
  | "invalid_request"
  | "authentication_failed"
  | "permission_denied"
  | "endpoint_or_model_not_found"
  | "response_uncertain"
  | "rate_or_quota_limited"
  | "provider_service_error"
  | "invalid_provider_output"
  | "delivery_uncertain"
  | "provider_error";

export interface ProviderFailureDetails {
  provider: "qwen" | "wanx";
  phase: ProviderFailurePhase;
  provider_http_status: number | null;
  safe_error_code: ProviderSafeErrorCode;
  request_id_digest: string | null;
  uncertain: boolean;
  potentially_billable: boolean;
  occurred_at: string;
}

export interface CampaignMetrics {
  impressions: number;
  clicks: number;
  conversions: number;
  spend: number;
  revenue: number;
  ctr: number;
  conversion_rate: number;
  cpa: number | null;
  roas: number | null;
}

export type GrowthMetric =
  | "ctr"
  | "conversion_rate"
  | "cpa"
  | "roas";

export interface GrowthObservation {
  scope: "overall" | "platform";
  platform: "TikTok" | "Instagram" | "Facebook" | null;
  metric: GrowthMetric;
  direction: "improve" | "test" | "protect" | "investigate";
  hypothesis: string;
}

export interface GrowthCopyConstraint {
  platform: "TikTok" | "Instagram" | "Facebook";
  hook_direction: string;
  message_angle: string;
  cta_direction: string;
  must_preserve: string[];
  must_avoid: string[];
}

export interface GrowthVideoConstraint {
  platform: "TikTok" | "Instagram" | "Facebook";
  opening_hook_direction: string;
  visual_focus: string;
  pacing_direction: string;
  cta_direction: string;
  must_preserve: string[];
  must_avoid: string[];
}

export interface GrowthRecommendation {
  problems: string[];
  recommendations: string[];
  budget_suggestion: string;
  creative_suggestions: string[];
}

export interface GrowthRecommendationConstraints {
  summary: string;
  observations: GrowthObservation[];
  copy_constraints: GrowthCopyConstraint[];
  video_constraint: GrowthVideoConstraint;
  budget_guidance: string;
}

export interface GrowthRecommendationPreflight {
  product_id: number;
  context_digest: string;
  marketing_strategy_id: number | null;
  copy_matrix_id: number | null;
  video_project_id: number | null;
  input_ready: boolean;
  provider_configured: boolean;
  execution_enabled: boolean;
  contract_ready: boolean;
  ready_for_execution: boolean;
  missing_requirements: string[];
  provider_label: string;
  model_label: string;
  preflight_only: true;
  execution_will_call_ai: true;
  execution_will_write_database: false;
  execution_will_generate_copy: false;
  execution_will_generate_video: false;
  automatic_action_allowed: false;
  cost_notice: string;
  attribution_notice: string;
}

export interface GrowthAnalysis {
  version: "v1";
  product_id: number;
  source_context_digest: string;
  source_marketing_strategy_id: number;
  source_copy_matrix_id: number;
  source_video_project_id: number;
  recommendation: GrowthRecommendationConstraints;
  recommendation_digest: string;
  recommendation_integrity_scope:
    "deterministic_round_trip_not_authenticated";
  recommendation_only: true;
  recommendation_persisted: false;
  campaign_association_scope: "product_only";
  causal_attribution_allowed: false;
  automatic_action_allowed: false;
  budget_change_allowed: false;
  copy_generation_triggered: false;
  video_generation_triggered: false;
  provider_calls: 1;
}

export interface FeedbackPlatformMetrics {
  platform: string;
  metrics: CampaignMetrics;
}

export interface FeedbackContext {
  version: "v1";
  product_id: number;
  data_source: "stored_campaigns";
  context_digest: string;
  feedback_only: true;
  recommendation_generated: false;
  generation_triggered: false;
  provider_calls: 0;
  campaign_ids: number[];
  campaign_count: number;
  date_from: string | null;
  date_to: string | null;
  platforms: string[];
  overall_metrics: CampaignMetrics | null;
  platform_metrics: FeedbackPlatformMetrics[];
  marketing_strategy_id: number | null;
  copy_matrix_id: number | null;
  video_project_id: number | null;
  content_chain_ready: boolean;
  content_chain_selection: "latest_video_project_exact_chain";
  campaign_association_scope: "product_only";
  creative_attribution_persisted: false;
  marketing_brief_attribution_persisted: false;
  association_notice: string;
  context_ready: boolean;
  metrics_ready: boolean;
  missing_requirements: string[];
}
