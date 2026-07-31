import type { GrowthRecommendationConstraints } from "./growth";

export interface VideoProjectRequest {
  platform: string;
  duration_seconds: number;
  aspect_ratio: string;
}

export interface VideoScene {
  sequence: number;
  duration_seconds: number;
  shot_type: string;
  visual_description: string;
  action: string;
  narration: string;
}

export interface VideoProject extends VideoProjectRequest {
  id: number;
  product_id: number;
  marketing_strategy_id: number;
  copy_matrix_id: number;
  title: string;
  concept: string;
  scenes: VideoScene[];
  cta: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface V2VideoProjectSourceRequest {
  source_context_digest: string;
  source_marketing_strategy_id: number;
  source_copy_matrix_id: number;
  source_video_project_id: number;
  recommendation_digest: string;
  recommendation: GrowthRecommendationConstraints;
  candidate_copy_matrix_id: number;
}

export interface V2VideoProjectExecutionRequest
  extends V2VideoProjectSourceRequest {
  expected_preflight_digest: string;
}

export interface V2VideoProjectPreflight {
  product_id: number;
  source_context_digest: string;
  source_recommendation_digest: string;
  source_marketing_strategy_id: number;
  source_copy_matrix_id: number;
  source_video_project_id: number;
  candidate_copy_matrix_id: number;
  platform: string;
  duration_seconds: number;
  aspect_ratio: string;
  input_ready: boolean;
  provider_configured: boolean;
  v2_video_project_execution_enabled: boolean;
  contract_ready: boolean;
  ready_for_execution: boolean;
  missing_requirements: string[];
  preflight_digest: string;
  preflight_only: true;
  execution_will_call_qwen: true;
  execution_will_create_video_project: true;
  execution_will_call_wanx: false;
  execution_will_create_render_task: false;
  execution_will_create_artifact: false;
  automatic_action_allowed: false;
  cost_notice: string;
  association_notice: string;
}

export interface V2VideoProjectExecutionResult {
  version: "v2-video-project-candidate-v1";
  product_id: number;
  source_context_digest: string;
  source_recommendation_digest: string;
  source_marketing_strategy_id: number;
  source_copy_matrix_id: number;
  source_video_project_id: number;
  candidate_copy_matrix_id: number;
  generated_video_project: VideoProject;
  provider_calls: 1;
  wanx_calls: 0;
  render_tasks_created: 0;
  artifacts_created: 0;
  source_video_project_modified: false;
  source_copy_modified: false;
  candidate_copy_modified: false;
  recommendation_persisted: false;
  candidate_copy_matrix_association_persisted: true;
  candidate_copy_source_parent_relation_persisted: false;
  source_video_parent_relation_persisted: false;
  rendered: false;
  automatic_action_allowed: false;
  association_notice: string;
}

export interface VideoRenderPreflight {
  video_project_id: number;
  product_id: number;
  marketing_strategy_id: number;
  copy_matrix_id: number;
  input_ready: boolean;
  provider: "Wanx";
  provider_configured: boolean;
  execution_enabled: boolean;
  artifact_storage_configured: boolean;
  contract_ready: boolean;
  ready_for_execution: boolean;
  missing_requirements: string[];
  platform: string;
  duration_seconds: number;
  aspect_ratio: string;
  scene_count: number;
  project_status: string;
  preflight_only: true;
  estimated_cost_notice: string;
  association_notice: string;
}

export interface VideoRenderArtifact {
  id: number;
  video_render_task_id: number;
  provider_output_url: string | null;
  storage_path: string | null;
  metadata: Record<string, unknown>;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export type VideoRenderTaskStatus =
  | "CREATED"
  | "SUBMITTING"
  | "SUBMITTED"
  | "PENDING"
  | "RUNNING"
  | "REFRESHING"
  | "SUCCEEDED"
  | "FAILED"
  | "SUBMIT_UNKNOWN"
  | "ARTIFACT_PERSIST_FAILED"
  | "CANCELED";

export interface VideoRenderTask {
  id: number;
  video_project_id: number;
  scene_sequence: number;
  status: VideoRenderTaskStatus;
  provider_name: string | null;
  provider_task_id: string | null;
  render_prompt: string;
  duration_seconds: number;
  aspect_ratio: string;
  resolution: string;
  idempotency_key: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface LiveRenderTaskResponse {
  task: VideoRenderTask;
  artifact: VideoRenderArtifact | null;
  external_call: boolean;
}

export interface VideoRenderTaskSafe {
  id: number;
  video_project_id: number;
  scene_sequence: number;
  status: VideoRenderTaskStatus;
  provider_name: string | null;
  duration_seconds: number;
  aspect_ratio: string;
  resolution: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface VideoRenderArtifactReference {
  id: number;
  video_render_task_id: number;
  created_at: string;
  updated_at: string;
}

export interface VideoRenderArtifactSafe
  extends VideoRenderArtifactReference {
  provider: string;
  content_available: true;
  content_url: string;
  download_url: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  storage_kind: "local_filesystem";
}

export type VideoRenderRecoveryCategory =
  | "created"
  | "submit_uncertain"
  | "active"
  | "refresh_uncertain"
  | "terminal_failure"
  | "artifact_persist_failed"
  | "succeeded"
  | "succeeded_artifact_unavailable";

export type VideoRenderArtifactState =
  | "not_applicable"
  | "available"
  | "missing"
  | "invalid";

export interface VideoRenderRecoveryDecision {
  category: VideoRenderRecoveryCategory;
  artifact_state: VideoRenderArtifactState;
  read_only_retry_allowed: boolean;
  continue_original_submit_allowed: boolean;
  explicit_refresh_allowed: boolean;
  resubmit_forbidden: boolean;
  presentation_fallback_available: boolean;
  automatic_action_allowed: false;
  user_message: string;
}

export interface VideoRenderOperation {
  video_project_id: number;
  product_id: number;
  marketing_strategy_id: number;
  copy_matrix_id: number;
  task: VideoRenderTaskSafe;
  artifact: VideoRenderArtifactReference | null;
  reused: boolean;
  external_call: boolean;
  recovered: boolean;
  recovery: VideoRenderRecoveryDecision;
  association_notice: string;
}
