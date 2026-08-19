import type { ExecutionJob, ExecutionJobCreateResult } from "./execution";

export type ScriptSourceType = "MANUAL" | "VIDEO_PROJECT_IMPORT" | "QWEN_GENERATED";
export type EditableScriptSourceType = Exclude<ScriptSourceType, "QWEN_GENERATED">;

export interface StoryboardSceneDraft {
  sequence: number; start_ms: number; end_ms: number; shot_type: string;
  visual_description: string; action_description: string; narration: string; subtitle_draft: string;
}

export interface VideoScriptDraft {
  source_type: EditableScriptSourceType; idempotency_key: string; parent_version_id: number | null;
  strategy_id: number | null; copy_matrix_id: number | null; source_video_project_id: number | null;
  title: string; concept: string; hook: string; cta: string; scenes: StoryboardSceneDraft[];
}

export interface VideoScriptPreflight {
  variant_id: number; source_digest: string; content_digest: string; preflight_digest: string;
  expires_at: string; full_narration: string; full_subtitle_draft: string;
  current_stage_cost: string; cost_scope: "manual_versioning_only";
  provider_call_count: 0; database_writes: 0; review_status: "UNREVIEWED";
}

export interface StoryboardSceneVersion extends StoryboardSceneDraft { id: number; video_script_version_id: number; }
export interface VideoScriptVersion {
  id: number; batch_video_variant_id: number; version_number: number; parent_version_id: number | null;
  source_type: ScriptSourceType; source_digest: string; content_digest: string; idempotency_key: string;
  title: string; concept: string; hook: string; full_narration: string; cta: string;
  full_subtitle_draft: string; platform: string; language: string; creative_angle: string | null;
  brand_kit_version_id: number | null; brand_kit_version_digest: string | null;
  created_by_kind: "LOCAL_USER" | "SYSTEM_IMPORT" | "QWEN_PROVIDER"; review_status: "UNREVIEWED";
  source_execution_job_id: number | null; prompt_snapshot_json: Record<string, unknown> | null;
  prompt_digest: string | null; provider_name: string | null; provider_model: string | null;
  provider_response_digest: string | null;
  created_at: string; scenes: StoryboardSceneVersion[];
  is_active: boolean;
}
export interface VideoScriptCreateResult { version: VideoScriptVersion; reused: boolean; }
export interface VideoScriptActivation { variant_id: number; active_script_version_id: number; editing_state: "ACTIVE_VERSION"; reused: boolean; }

export interface QwenScriptPreflightRequest {
  idempotency_key: string; strategy_id: number; copy_matrix_id: number | null; parent_version_id: number | null;
}
export interface QwenScriptPreflight {
  ready_for_execution: boolean; variant_id: number; variant_source_digest: string;
  product_id: number; product_content_digest: string; strategy_id: number; strategy_digest: string;
  copy_matrix_id: number | null; target_platform_copy_digest: string | null;
  parent_version_id: number | null; parent_content_digest: string | null;
  brand_kit_version_id: number | null; brand_kit_version_digest: string | null;
  platform: string; language: string; creative_angle: string | null; duration_ms: 15000; aspect_ratio: "9:16";
  prompt_contract_version: string; output_schema_version: string; provider_name: "qwen"; provider_model: string;
  frozen_input_digest: string; preflight_digest: string; expires_at: string; estimated_provider_calls: 1;
  estimated_cost_min: string | null; estimated_cost_max: string | null; currency: string;
  cost_estimate_basis: string | null; cost_scope: "single_qwen_video_script_generation";
  requires_cost_confirmation: true; will_auto_activate: false; provider_call_count: 0; database_writes: 0;
  quota_limit: number; quota_reserved: number; quota_remaining: number;
}
export type QwenScriptJobCreateResult = ExecutionJobCreateResult;
export type QwenScriptJob = ExecutionJob;
