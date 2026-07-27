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
  provider_task_id: string | null;
  duration_seconds: number;
  aspect_ratio: string;
  resolution: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface VideoRenderArtifactSafe {
  id: number;
  video_render_task_id: number;
  available: true;
  content_url: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  updated_at: string;
}

export interface VideoRenderOperation {
  video_project_id: number;
  product_id: number;
  marketing_strategy_id: number;
  copy_matrix_id: number;
  task: VideoRenderTaskSafe;
  artifact: VideoRenderArtifactSafe | null;
  reused: boolean;
  external_call: boolean;
  recovered: boolean;
  association_notice: string;
}
