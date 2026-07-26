export interface PlatformCopy {
  platform: "TikTok" | "Instagram" | "Facebook";
  hook: string;
  caption: string;
  hashtags: string[];
  cta: string;
}

export interface CopyMatrix {
  product_id: number;
  copies: PlatformCopy[];
}

export interface PersistedCopyMatrix extends CopyMatrix {
  id: number;
  marketing_strategy_id: number;
  created_at: string;
}

export interface CopyExecutionResult {
  source_task_id: number;
  source_strategy_id: number;
  source_product_id: number;
  source_kind: "marketing_brief_and_strategy";
  requested_platforms: PlatformCopy["platform"][];
  copy_matrix: PersistedCopyMatrix;
  strategy_association_persisted: true;
  brief_association_persisted: false;
  association_notice: string;
}

export type CopyExecutionIssueCategory =
  | "execution-disabled"
  | "configuration"
  | "association"
  | "authentication"
  | "quota"
  | "network"
  | "invalid-output"
  | "platform-mismatch"
  | "backend"
  | "not-found"
  | "unknown";

export interface CopyExecutionIssue {
  category: CopyExecutionIssueCategory;
  message: string;
  retryable: boolean;
}

export interface CopyPreflightProductSummary {
  id: number;
  name: string;
  category: string;
  description: string;
  selling_points: string[];
}

export interface CopyPreflightStrategySummary {
  id: number;
  positioning: string;
  audience_insights_count: number;
  angles_count: number;
  risks_count: number;
  evidence_count: number;
}

export interface CopyPreflight {
  task_id: number;
  strategy_id: number;
  product_id: number;
  ready: boolean;
  input_ready: boolean;
  provider_configured: boolean;
  execution_enabled: boolean;
  contract_ready: boolean;
  ready_for_execution: boolean;
  missing_requirements: string[];
  platforms: string[];
  product_summary: CopyPreflightProductSummary;
  strategy_summary: CopyPreflightStrategySummary;
  association_persisted: false;
  association_notice: string;
  preflight_only: true;
  execution_will_call_ai: true;
  execution_will_create_copy_matrix: true;
  cost_notice: string;
}
