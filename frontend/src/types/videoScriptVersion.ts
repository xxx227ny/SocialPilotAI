export type ScriptSourceType = "MANUAL" | "VIDEO_PROJECT_IMPORT";

export interface StoryboardSceneDraft {
  sequence: number; start_ms: number; end_ms: number; shot_type: string;
  visual_description: string; action_description: string; narration: string; subtitle_draft: string;
}

export interface VideoScriptDraft {
  source_type: ScriptSourceType; idempotency_key: string; parent_version_id: number | null;
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
  created_by_kind: "LOCAL_USER" | "SYSTEM_IMPORT"; review_status: "UNREVIEWED";
  created_at: string; scenes: StoryboardSceneVersion[];
  is_active: boolean;
}
export interface VideoScriptCreateResult { version: VideoScriptVersion; reused: boolean; }
export interface VideoScriptActivation { variant_id: number; active_script_version_id: number; editing_state: "ACTIVE_VERSION"; reused: boolean; }
