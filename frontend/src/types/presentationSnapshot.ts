export type PresentationSnapshotSection =
  | "marketing_brief"
  | "marketing_strategy"
  | "copy_matrix"
  | "video_project"
  | "render_task"
  | "artifact"
  | "publish_task"
  | "campaigns";

export interface PresentationSnapshotCreateRequest {
  marketing_brief_id: number | null;
  marketing_strategy_id: number | null;
  copy_matrix_id: number | null;
  video_project_id: number | null;
  render_task_id: number | null;
  artifact_id: number | null;
  publish_task_id: number | null;
  campaign_ids: number[];
}

export interface PresentationSnapshot {
  id: number;
  schema_version: number;
  digest: string;
  product_id: number;
  marketing_brief_id: number | null;
  marketing_strategy_id: number | null;
  copy_matrix_id: number | null;
  video_project_id: number | null;
  render_task_id: number | null;
  artifact_id: number | null;
  publish_task_id: number | null;
  campaign_ids: number[];
  missing_sections: PresentationSnapshotSection[];
  snapshot_payload: Record<string, unknown>;
  artifact_sha256: string | null;
  artifact_snapshot_path: string | null;
  created_at: string;
}

export interface PresentationSnapshotCreateResult {
  snapshot: PresentationSnapshot;
  reused: boolean;
  provider_calls: 0;
}
