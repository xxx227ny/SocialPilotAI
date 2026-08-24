import type { ExecutionJob } from "./execution";
import type { QwenScriptPreflight } from "./videoScriptVersion";

export type BatchPlatform = "youtube" | "tiktok" | "instagram";
export type BatchVariantStatus =
  | "WAITING"
  | "RUNNING"
  | "READY_FOR_SCRIPT"
  | "PAUSED"
  | "FAILED"
  | "CANCELLED";

export interface BatchVideoRequest {
  product_ids: number[];
  platforms: BatchPlatform[];
  variants_per_platform: number;
  duration_seconds: 15;
  aspect_ratio: "9:16";
  language: string;
  priority: number;
  max_concurrency: number;
  creative_angle: string | null;
  idempotency_key: string;
}

export interface BatchVideoPreflight {
  ready: boolean;
  request_digest: string;
  preflight_digest: string;
  expires_at: string;
  variant_count: number;
  max_concurrency: number;
  current_stage_cost: string;
  currency: string;
  cost_scope: "orchestration_only";
  downstream_provider_cost_status: "NOT_ESTIMATED";
  provider_call_count: 0;
  ffmpeg_call_count: 0;
}

export interface BatchVideoJob {
  id: number;
  request_digest: string;
  idempotency_key: string;
  status: string;
  priority: number;
  variant_count: number;
  max_concurrency: number;
  current_stage_cost: string;
  currency: string;
  cost_scope: string;
  downstream_provider_cost_status: string;
  qwen_script_call_quota: number;
  qwen_script_calls_reserved: number;
}

export interface BatchVideoVariant {
  id: number;
  batch_video_job_id: number;
  product_id: number;
  platform: BatchPlatform;
  variant_index: number;
  brand_kit_version_id: number | null;
  execution_job_id: number;
  status: BatchVariantStatus;
  safe_error_code: string | null;
  active_script_version_id: number | null;
  script_version_sequence: number;
}

export interface BatchVideoCreateResult {
  batch: BatchVideoJob;
  variants: BatchVideoVariant[];
  reused: boolean;
}

export interface BatchProductOption {
  id: number;
  name: string;
  brand_kit_version_id: number | null;
}

export interface BatchQwenScriptRequest {
  product_id: number;
  variant_ids: number[];
  strategy_id: number;
  copy_matrix_id: number | null;
}

export interface BatchQwenScriptPreflight extends BatchQwenScriptRequest {
  batch_id: number;
  items: QwenScriptPreflight[];
  preflight_digest: string;
  expires_at: string;
  ready_for_execution: boolean;
  estimated_provider_calls: number;
  estimated_cost_min: string;
  estimated_cost_max: string;
  wanx_image_generation_calls: number;
  happyhorse_generation_calls: number;
  qwen_tts_generation_calls: number;
  known_downstream_cost: string;
  total_known_cost_min: string;
  total_known_cost_max: string;
  currency: string;
  cost_estimate_basis: string;
  cost_estimate_complete: false;
  unpriced_cost_components: string[];
  requires_cost_confirmation: true;
  will_auto_activate_exact_results: true;
  provider_call_count: 0;
  database_writes: 0;
}

export interface BatchQwenScriptItem {
  variant_id: number;
  platform: BatchPlatform;
  status: "QUEUED" | "RUNNING" | "READY" | "FAILED" | "SUBMIT_UNKNOWN";
  job: ExecutionJob;
  script_version_id: number | null;
  active: boolean;
  safe_error_code: string | null;
}

export interface BatchQwenScriptResult {
  batch_id: number;
  status: "RUNNING" | "READY" | "PARTIAL_FAILED" | "FAILED";
  items: BatchQwenScriptItem[];
}
