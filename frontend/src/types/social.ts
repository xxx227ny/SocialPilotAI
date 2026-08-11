export type SocialConnectionStatus =
  | "CONNECTED"
  | "DISCONNECTED"
  | "EXPIRED"
  | "FAILED";

export interface SocialAccount {
  id: number;
  product_id: number;
  platform: "youtube";
  provider_account_id: string;
  display_name: string;
  scopes: string[];
  connection_status: SocialConnectionStatus;
  token_expires_at: string | null;
  created_at: string;
  updated_at: string;
  disconnected_at: string | null;
}

export interface YouTubeConnectResult {
  authorization_url: string;
  expires_at: string;
}

export interface PublishArtifactCandidate {
  artifact_id: number;
  render_task_id: number;
  video_project_id: number;
  copy_matrix_id: number;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
}

export interface YouTubePublishingMetadata {
  social_account_id: number;
  artifact_id: number;
  title: string;
  description: string;
  tags: string[];
  privacy_status: "private";
  made_for_kids: boolean | null;
  synthetic_media: true;
  notify_subscribers: false;
}

export interface YouTubePreflight {
  status: "READY" | "BLOCKED";
  ready: boolean;
  missing_requirements: string[];
  preflight_digest: string;
  input_digest: string;
  expires_at: string;
  product_id: number;
  social_account_id: number;
  channel_id: string;
  artifact_id: number;
  render_task_id: number;
  video_project_id: number;
  copy_matrix_id: number;
  privacy_status: "private";
  synthetic_media: true;
  notify_subscribers: false;
  provider_calls: 0;
  database_writes: 0;
}

export interface PublishTask {
  id: number;
  product_id: number;
  social_account_id: number;
  artifact_id: number;
  platform: "youtube";
  title: string;
  description: string;
  tags: string[];
  privacy_status: "private";
  made_for_kids: boolean;
  synthetic_media: true;
  notify_subscribers: false;
  status: string;
  provider_video_id: string | null;
  safe_error_code: string | null;
  uncertain: boolean;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  completed_at: string | null;
}

export interface PublishExecution {
  task: PublishTask;
  reused: boolean;
  external_call: boolean;
}
