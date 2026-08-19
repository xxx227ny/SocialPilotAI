import { apiClient } from "./client";
import type { QwenScriptJob, QwenScriptJobCreateResult, QwenScriptPreflight, QwenScriptPreflightRequest, VideoScriptActivation, VideoScriptCreateResult, VideoScriptDraft, VideoScriptPreflight, VideoScriptVersion } from "../types/videoScriptVersion";

const base = (variantId: number) => `/batch-video-variants/${variantId}/script-versions`;
export async function preflightVideoScript(variantId: number, draft: VideoScriptDraft, signal?: AbortSignal) {
  return (await apiClient.post<VideoScriptPreflight>(`${base(variantId)}/preflight`, draft, { signal })).data;
}
export async function createVideoScriptVersion(variantId: number, draft: VideoScriptDraft, checked: VideoScriptPreflight, signal?: AbortSignal) {
  return (await apiClient.post<VideoScriptCreateResult>(base(variantId), { ...draft, source_digest: checked.source_digest, content_digest: checked.content_digest, preflight_digest: checked.preflight_digest, preflight_expires_at: checked.expires_at }, { signal })).data;
}
export async function listVideoScriptVersions(variantId: number, signal?: AbortSignal) {
  return (await apiClient.get<VideoScriptVersion[]>(base(variantId), { signal })).data;
}
export async function getVideoScriptVersion(variantId: number, versionId: number, signal?: AbortSignal) {
  return (await apiClient.get<VideoScriptVersion>(`${base(variantId)}/${versionId}`, { signal })).data;
}
export async function activateVideoScriptVersion(variantId: number, versionId: number, signal?: AbortSignal) {
  return (await apiClient.post<VideoScriptActivation>(`${base(variantId)}/${versionId}/activate`, undefined, { signal })).data;
}
export async function preflightQwenVideoScript(variantId: number, request: QwenScriptPreflightRequest, signal?: AbortSignal) {
  return (await apiClient.post<QwenScriptPreflight>(`/batch-video-variants/${variantId}/qwen-script/preflight`, request, { signal })).data;
}
export async function createQwenVideoScriptJob(variantId: number, request: QwenScriptPreflightRequest, checked: QwenScriptPreflight, signal?: AbortSignal) {
  return (await apiClient.post<QwenScriptJobCreateResult>(`/batch-video-variants/${variantId}/qwen-script/jobs`, {
    ...request,
    frozen_input_digest: checked.frozen_input_digest,
    preflight_digest: checked.preflight_digest,
    preflight_expires_at: checked.expires_at,
    estimated_cost_min: checked.estimated_cost_min,
    estimated_cost_max: checked.estimated_cost_max,
    currency: checked.currency,
    cost_estimate_basis: checked.cost_estimate_basis,
    cost_confirmed: true,
  }, { signal })).data;
}
export async function getQwenVideoScriptJob(jobId: number, signal?: AbortSignal) {
  return (await apiClient.get<QwenScriptJob>(`/execution-jobs/${jobId}`, { signal })).data;
}
