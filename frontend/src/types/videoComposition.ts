import type { ExecutionJob } from "./execution";

export interface CompositionShotInput {
  sequence: number;
  start_ms: number;
  end_ms: number;
  trim_start_ms: number;
  trim_end_ms: number;
  transition_type: "cut";
  render_task_id: number;
  artifact_id: number;
}

export interface VideoCompositionPreflight {
  product_id: number;
  video_project_id: number;
  shots: Array<CompositionShotInput & { artifact_sha256: string }>;
  input_digest: string;
  source_chain_digest: string;
  preflight_digest: string;
  expires_at: string;
  ready: boolean;
  missing_requirements: string[];
  output_contract: Record<string, unknown>;
  execution_notice: string;
  placeholder_audio_notice: string;
}

export interface VideoCompositionArtifact {
  id: number;
  composition_id: number;
  content_type: "video/mp4";
  size_bytes: number;
  sha256: string;
  duration_ms: number;
  width: number;
  height: number;
  fps_numerator: number;
  fps_denominator: number;
  video_codec: string;
  pixel_format: string;
  audio_codec: string;
  audio_sample_rate: number;
}

export interface VideoComposition {
  id: number;
  product_id: number;
  video_project_id: number;
  input_digest: string;
  source_chain_digest: string;
  status: string;
  shots: CompositionShotInput[];
  artifact: VideoCompositionArtifact | null;
}

export interface VideoCompositionSubmitResult {
  composition: VideoComposition;
  job: ExecutionJob;
  reused: boolean;
}
