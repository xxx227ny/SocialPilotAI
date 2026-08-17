import { apiClient } from "./client";
import type { VideoScriptActivation, VideoScriptCreateResult, VideoScriptDraft, VideoScriptPreflight, VideoScriptVersion } from "../types/videoScriptVersion";

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
