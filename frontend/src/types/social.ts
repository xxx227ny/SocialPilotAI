export type SocialConnectionStatus =
  | "CONNECTED"
  | "DISCONNECTED"
  | "EXPIRED"
  | "FAILED";

export interface SocialAccount {
  id: number;
  product_id: number;
  platform: "youtube" | "instagram" | "tiktok" | "pinterest";
  provider_account_id: string;
  display_name: string;
  scopes: string[];
  connection_status: SocialConnectionStatus;
  token_expires_at: string | null;
  refresh_token_expires_at: string | null;
  created_at: string;
  updated_at: string;
  disconnected_at: string | null;
}

export interface YouTubeConnectResult {
  authorization_url: string;
  expires_at: string;
}

export interface InstagramConnectResult {
  authorization_url: string;
  expires_at: string;
}

export interface TikTokConnectResult {
  authorization_url: string;
  expires_at: string;
}

export interface PinterestConnectResult {
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
  platform: "youtube" | "instagram" | "tiktok" | "pinterest";
  title: string;
  description: string;
  tags: string[];
  privacy_status: "private" | "public";
  made_for_kids: boolean;
  synthetic_media: true;
  notify_subscribers: false;
  share_to_feed: boolean;
  status: string;
  provider_video_id: string | null;
  provider_publish_id: string | null;
  safe_error_code: string | null;
  uncertain: boolean;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  completed_at: string | null;
  disable_comment: boolean;
  disable_duet: boolean;
  disable_stitch: boolean;
  brand_content_toggle: boolean;
  brand_organic_toggle: boolean;
}

export interface TikTokCreatorInfoSnapshot {
  id: number; product_id: number; social_account_id: number;
  creator_username: string; creator_nickname: string;
  privacy_level_options: string[]; comment_disabled: boolean;
  duet_disabled: boolean; stitch_disabled: boolean;
  max_video_post_duration_sec: number; fetched_at: string; expires_at: string;
}

export interface TikTokPublishingMetadata {
  social_account_id: number; creator_info_snapshot_id: number; artifact_id: number;
  title: string;
  description: string; tags: string[]; privacy_status: string;
  disable_comment: boolean; disable_duet: boolean; disable_stitch: boolean;
  brand_content_toggle: boolean; brand_organic_toggle: boolean;
}

export interface TikTokPublishPreflight {
  status: "READY" | "BLOCKED"; ready: boolean; missing_requirements: string[];
  input_digest: string; preflight_digest: string; expires_at: string;
  product_id: number; social_account_id: number; creator_info_snapshot_id: number;
  artifact_id: number; render_task_id: number; video_project_id: number;
  copy_matrix_id: number; marketing_strategy_id: number;
  content_type: "video/mp4" | "video/quicktime"; size_bytes: number; sha256: string;
  safe_path_digest: string;
  caption_length_utf16: number; provider_calls: 0; database_writes: 0;
}

export interface InstagramPublishingMetadata {
  social_account_id: number;
  artifact_id: number;
  title: string;
  description: string;
  tags: string[];
  privacy_status: "public";
  made_for_kids: false;
  synthetic_media: true;
  notify_subscribers: false;
  share_to_feed: boolean;
}

export interface InstagramPublishPreflight {
  status: "READY" | "BLOCKED";
  ready: boolean;
  missing_requirements: string[];
  input_digest: string;
  preflight_digest: string;
  expires_at: string;
  product_id: number;
  social_account_id: number;
  artifact_id: number;
  render_task_id: number;
  video_project_id: number;
  copy_matrix_id: number;
  marketing_strategy_id: number;
  content_type: "video/mp4" | "video/quicktime";
  size_bytes: number;
  sha256: string;
  caption_length: number;
  share_to_feed: boolean;
  provider_calls: 0;
  database_writes: 0;
}

export interface InstagramFinalizePreflight {
  ready: true;
  product_id: number;
  social_account_id: number;
  publish_task_id: number;
  input_digest: string;
  preflight_digest: string;
  expires_at: string;
  provider_calls: 0;
  database_writes: 0;
}

export interface PublishExecution {
  task: PublishTask;
  reused: boolean;
  external_call: boolean;
}
