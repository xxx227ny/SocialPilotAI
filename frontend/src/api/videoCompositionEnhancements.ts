import { apiClient, apiContentUrl } from "./client";
import type { ExecutionJob } from "../types/execution";
import type {
  CompositionAudioArtifact,
  CompositionEnhancementArtifact,
  CompositionEnhancementPreflight,
  CompositionEnhancementSubmitResult,
  EnhancementInput,
} from "../types/videoCompositionEnhancement";

export async function listCompositionAudioArtifacts(productId: number, compositionId: number, signal?: AbortSignal) {
  const response = await apiClient.get<CompositionAudioArtifact[]>(`/products/${productId}/video-compositions/${compositionId}/audio-artifacts`, { signal });
  return response.data;
}

export async function preflightCompositionEnhancement(productId: number, input: EnhancementInput, signal?: AbortSignal) {
  const response = await apiClient.post<CompositionEnhancementPreflight>(`/products/${productId}/video-composition-enhancements/preflight`, input, { signal });
  return response.data;
}

export async function submitCompositionEnhancement(productId: number, preflight: CompositionEnhancementPreflight, signal?: AbortSignal) {
  const response = await apiClient.post<CompositionEnhancementSubmitResult>(`/products/${productId}/video-composition-enhancements`, {
    composition_id: preflight.composition_id,
    source_artifact_id: preflight.source_artifact_id,
    voiceover_artifact_id: preflight.voiceover_artifact_id,
    music_artifact_id: preflight.music_artifact_id,
    cues: preflight.cues,
    style: preflight.style,
    mix: preflight.mix,
    input_digest: preflight.input_digest,
    source_chain_digest: preflight.source_chain_digest,
    preflight_digest: preflight.preflight_digest,
    preflight_expires_at: preflight.expires_at,
    local_cpu_cost_confirmed: true,
  }, { signal });
  return response.data;
}

export async function getCompositionEnhancementJob(jobId: number, signal?: AbortSignal) {
  const response = await apiClient.get<ExecutionJob>(`/execution-jobs/${jobId}`, { signal });
  return response.data;
}

export async function getCompositionEnhancementArtifact(artifactId: number, signal?: AbortSignal) {
  const response = await apiClient.get<CompositionEnhancementArtifact>(`/video-composition-enhancement-artifacts/${artifactId}`, { signal });
  return response.data;
}

export const compositionEnhancementContentUrl = (artifactId: number) =>
  apiContentUrl(`/video-composition-enhancement-artifacts/${artifactId}/content`);
export const compositionEnhancementPreviewUrl = (artifactId: number) =>
  apiContentUrl(`/video-composition-enhancement-artifacts/${artifactId}/preview`);
export const compositionSubtitleContentUrl = (artifactId: number) =>
  apiContentUrl(`/video-composition-subtitle-artifacts/${artifactId}/content`);
