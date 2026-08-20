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

export type RealProductVideoPhase =
  | "IDLE"
  | "UPLOADING"
  | "GENERATING_IMAGES"
  | "PREPARING_SHOTS"
  | "CLOUD_VIDEO"
  | "COMPOSING"
  | "VOICEOVER"
  | "ENHANCING"
  | "SUCCEEDED"
  | "FAILED";
