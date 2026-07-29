export interface CampaignUploadResponse {
  product_id: number;
  imported_count: number;
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

export interface GrowthRecommendation {
  problems: string[];
  recommendations: string[];
  budget_suggestion: string;
  creative_suggestions: string[];
}

export interface GrowthAnalysis {
  metrics: CampaignMetrics;
  recommendation: GrowthRecommendation;
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
