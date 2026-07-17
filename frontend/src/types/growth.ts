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
