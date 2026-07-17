import type { CampaignMetrics, GrowthRecommendation } from "./growth";
import type { Product } from "./product";
import type { PlatformCopy } from "./copy";
import type { VideoProject } from "./video";

export type PipelineStatus = "complete" | "partial" | "missing";

export interface DashboardStrategy {
  id: number;
  product_id: number;
  positioning: string;
  audience_insights: string[];
  angles: string[];
  risks: string[];
  evidence: string[];
  created_at: string;
}

export interface DashboardCopyMatrix {
  id: number;
  product_id: number;
  marketing_strategy_id: number;
  copies: PlatformCopy[];
  created_at: string;
}

export interface DashboardGrowth {
  status: PipelineStatus;
  metrics: CampaignMetrics | null;
  platform_metrics: PlatformMetrics[];
  recommendation: GrowthRecommendation | null;
}

export interface PlatformMetrics {
  platform: string;
  metrics: CampaignMetrics;
}

export interface PipelineStep {
  key: "product" | "strategy" | "copy" | "video" | "growth";
  label: string;
  status: PipelineStatus;
  source_id: number | null;
}

export interface DemoMetadata {
  slug: string;
  label: string;
  source: "preset_fixture";
  fixture_version: number;
  badge: "Demo Snapshot";
  ai_calls: 0;
  notice: "使用预置演示数据";
}

export interface DashboardSnapshot {
  data_source: "stored_records" | "demo_snapshot";
  demo: DemoMetadata | null;
  product: Product;
  strategy: DashboardStrategy | null;
  copy_matrix: DashboardCopyMatrix | null;
  video_project: VideoProject | null;
  growth: DashboardGrowth;
  pipeline: PipelineStep[];
}
