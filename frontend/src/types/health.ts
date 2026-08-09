export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
}

export interface SystemReadinessItem {
  ready: boolean;
  message: string;
}

export interface DatabaseReadinessItem extends SystemReadinessItem {
  revision_status: "head" | "upgrade_required" | "unavailable";
  revision: string | null;
}

export interface SystemReadinessResponse {
  backend: SystemReadinessItem;
  qwen: SystemReadinessItem;
  wanx: SystemReadinessItem;
  google_youtube: SystemReadinessItem;
  database: DatabaseReadinessItem;
  artifact_storage: SystemReadinessItem;
  provider_calls: 0;
  database_writes: 0;
  automatic_actions: false;
}
