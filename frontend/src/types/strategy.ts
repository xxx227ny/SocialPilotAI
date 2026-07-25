export interface MarketingStrategy {
  id: number;
  product_id: number;
  positioning: string;
  audience_insights: string[];
  angles: string[];
  risks: string[];
  evidence: string[];
  created_at: string;
}

export type StrategyExecutionIssueCategory =
  | "configuration"
  | "authentication"
  | "quota"
  | "network"
  | "invalid-output"
  | "backend"
  | "not-found"
  | "unknown";

export interface StrategyExecutionIssue {
  category: StrategyExecutionIssueCategory;
  message: string;
  retryable: boolean;
}

export interface StrategyPreflightProductSummary {
  id: number;
  name: string;
  category: string;
  description: string;
  selling_points: string[];
}

export interface StrategyPreflight {
  task_id: number;
  product_id: number;
  ready: boolean;
  missing_requirements: string[];
  product_summary: StrategyPreflightProductSummary;
  target_market_snapshot: string[];
  platforms: string[];
  audience: string;
  language: string;
  tone: string;
  objective: string;
  provider_label: string;
  model_label: string;
  provider_configured: boolean;
  preflight_only: boolean;
  execution_will_call_ai: boolean;
  execution_will_create_strategy: boolean;
  cost_notice: string;
}
