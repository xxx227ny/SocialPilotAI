import type { ExecutionJob } from "./execution";

export interface ProductVideoScene {
  id: number;
  sequence: number;
  start_ms: number;
  end_ms: number;
  visual_description: string;
  action_description: string;
  narration: string;
  subtitle_draft: string;
}

export interface ProductVideoSource {
  variant_id: number;
  script_version_id: number;
  platform: "youtube" | "tiktok" | "instagram";
  language: string;
  content_digest: string;
  scenes: ProductVideoScene[];
}

export interface UploadedProductImage {
  id: number;
  product_id: number;
  file_name: string;
  file_type: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  width: number;
  height: number;
  created_at: string;
  reused: boolean;
}

export interface ProductVideoPrepare {
  video_project_id: number;
  script_version_id: number;
  reused: boolean;
  input_digest: string;
  tts_notice: string;
}

export interface MarketingJobResult {
  job: ExecutionJob;
  reused: boolean;
}

export interface HappyHorseVideoPreflight {
  video_project_id: number;
  script_version_id: number;
  reference_images: Array<{
    product_asset_id: number;
    product_asset_sha256: string;
  }>;
  input_digest: string;
  preflight_digest: string;
  expires_at: string;
  ready: boolean;
  missing_requirements: string[];
}

export interface ThreePlatformVideoPreflight {
  reference_product_asset_id: number;
  reference_product_asset_sha256: string;
  selections: Array<{ variant_id: number; script_version_id: number }>;
  input_digest: string;
  platforms: Array<{
    platform: "tiktok" | "youtube" | "instagram";
    variant_id: number;
    script_version_id: number;
    scene_count: number;
    wanx_image_generation_calls: number;
    happyhorse_generation_calls: number;
    qwen_tts_generation_calls: number;
    known_estimated_cost: string;
    currency: "CNY";
  }>;
  wanx_image_generation_calls: number;
  happyhorse_generation_calls: number;
  qwen_tts_generation_calls: number;
  qwen_script_generation_calls: 0;
  known_estimated_cost: string;
  currency: "CNY";
  cost_estimate_complete: false;
  unpriced_cost_components: string[];
  requires_cost_confirmation: true;
  ready: boolean;
  missing_requirements: string[];
  provider_call_count: number;
  database_writes: 0;
}

export interface ProductVideoProductionBatch {
  id: number;
  product_id: number;
  reference_product_asset_id: number;
  reference_product_asset_sha256: string;
  input_digest: string;
  idempotency_key: string;
  status:
    | "WAITING"
    | "RUNNING"
    | "PAUSED"
    | "PARTIAL_FAILED"
    | "SUCCEEDED"
    | "FAILED"
    | "CANCELLED";
  known_estimated_cost: string;
  currency: string;
  cost_estimate_complete: boolean;
  cost_confirmed: boolean;
  provider_call_budget: number;
  safe_error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ProductVideoProductionItem {
  id: number;
  production_batch_id: number;
  batch_video_variant_id: number;
  script_version_id: number;
  platform: "tiktok" | "youtube" | "instagram";
  status: "WAITING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  stage:
    | "QUEUED"
    | "GENERATING_IMAGES"
    | "PREPARING_VIDEO"
    | "GENERATING_VIDEO"
    | "COMPOSING"
    | "GENERATING_VOICEOVER"
    | "ENHANCING"
    | "COMPLETE";
  stage_state_json: Record<string, unknown>;
  video_project_id: number | null;
  cloud_render_task_id: number | null;
  cloud_render_artifact_id: number | null;
  composition_id: number | null;
  voiceover_artifact_id: number | null;
  enhancement_id: number | null;
  final_video_artifact_id: number | null;
  subtitle_artifact_id: number | null;
  safe_error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ProductVideoProductionResult {
  batch: ProductVideoProductionBatch;
  items: ProductVideoProductionItem[];
  reused: boolean;
}

export type RealProductVideoPhase =
  | "IDLE"
  | "UPLOADING"
  | "GENERATING_SCRIPTS"
  | "GENERATING_IMAGES"
  | "PREPARING_SHOTS"
  | "CLOUD_VIDEO"
  | "COMPOSING"
  | "VOICEOVER"
  | "ENHANCING"
  | "SUCCEEDED"
  | "FAILED";
