import { apiClient, apiContentUrl } from "./client";
import type { ExecutionJob } from "../types/execution";
import type {
  CompositionShotInput,
  VideoCompositionArtifact,
  VideoCompositionPreflight,
  VideoCompositionSubmitResult,
} from "../types/videoComposition";

export async function preflightVideoComposition(productId: number, videoProjectId: number, shots: CompositionShotInput[], signal?: AbortSignal) {
  const response = await apiClient.post<VideoCompositionPreflight>(`/products/${productId}/video-compositions/preflight`, { video_project_id: videoProjectId, shots }, { signal });
  return response.data;
}

export async function submitVideoComposition(productId: number, preflight: VideoCompositionPreflight, signal?: AbortSignal) {
  const response = await apiClient.post<VideoCompositionSubmitResult>(`/products/${productId}/video-compositions`, {
    video_project_id: preflight.video_project_id,
    shots: preflight.shots.map((shot) => ({
      sequence: shot.sequence,
      start_ms: shot.start_ms,
      end_ms: shot.end_ms,
      trim_start_ms: shot.trim_start_ms,
      trim_end_ms: shot.trim_end_ms,
      transition_type: shot.transition_type,
      render_task_id: shot.render_task_id,
      artifact_id: shot.artifact_id,
    })),
    input_digest: preflight.input_digest,
    source_chain_digest: preflight.source_chain_digest,
    preflight_digest: preflight.preflight_digest,
    preflight_expires_at: preflight.expires_at,
    local_cpu_cost_confirmed: true,
  }, { signal });
  return response.data;
}

export async function getCompositionJob(jobId: number, signal?: AbortSignal) {
  const response = await apiClient.get<ExecutionJob>(`/execution-jobs/${jobId}`, { signal });
  return response.data;
}

export async function getCompositionArtifact(artifactId: number, signal?: AbortSignal) {
  const response = await apiClient.get<VideoCompositionArtifact>(`/video-composition-artifacts/${artifactId}`, { signal });
  return response.data;
}

export const compositionArtifactContentUrl = (artifactId: number) =>
  apiContentUrl(`/video-composition-artifacts/${artifactId}/content`);
export const compositionArtifactPreviewUrl = (artifactId: number) =>
  apiContentUrl(`/video-composition-artifacts/${artifactId}/preview`);
