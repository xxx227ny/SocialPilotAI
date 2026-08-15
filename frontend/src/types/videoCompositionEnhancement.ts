import type { ExecutionJob } from "./execution";

export interface CompositionAudioArtifact {
  id: number;
  product_id: number;
  video_project_id: number;
  composition_id: number;
  kind: "voiceover" | "music";
  content_type: string;
  size_bytes: number;
  sha256: string;
  duration_ms: number;
  created_at: string;
}

export interface SubtitleCueInput {
  sequence: number;
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface EnhancementInput {
  composition_id: number;
  source_artifact_id: number;
  voiceover_artifact_id: number;
  music_artifact_id: number | null;
  cues: SubtitleCueInput[];
  style: { font_size: number; max_chars_per_line: number; bottom_margin: number; outline_width: number };
  mix: { voiceover_gain_db: number; music_gain_db: number; ducking_reduction_db: number; target_lufs: number; true_peak_db: number };
}

export interface CompositionEnhancementPreflight extends EnhancementInput {
  product_id: number;
  video_project_id: number;
  source_artifact_sha256: string;
  input_digest: string;
  source_chain_digest: string;
  preflight_digest: string;
  expires_at: string;
  ready: boolean;
  missing_requirements: string[];
  execution_notice: string;
}

export interface CompositionSubtitleArtifact {
  id: number;
  enhancement_id: number;
  content_type: string;
  size_bytes: number;
  sha256: string;
  format: string;
  cue_count: number;
}

export interface CompositionEnhancementArtifact {
  id: number;
  enhancement_id: number;
  subtitle_artifact_id: number;
  content_type: string;
  size_bytes: number;
  sha256: string;
  duration_ms: number;
  video_codec: string;
  video_profile: string;
  audio_codec: string;
  audio_profile: string;
  audio_sample_rate: number;
  audio_channels: number;
  measured_lufs_milli: number;
  measured_true_peak_millidb: number;
  audio_video_sync_offset_ms: number;
  longest_black_segment_ms: number;
  subtitle_cue_count: number;
}

export interface CompositionEnhancementSubmitResult {
  enhancement: { id: number; status: string };
  job: ExecutionJob;
  reused: boolean;
}
