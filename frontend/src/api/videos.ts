import { AI_EXECUTION_TIMEOUT_MS, apiClient } from "./client";
import type {
  LiveRenderTaskResponse,
  VideoProject,
  VideoProjectRequest,
  VideoRenderArtifact,
  VideoRenderArtifactSafe,
  VideoRenderOperation,
  VideoRenderPreflight,
  V2VideoProjectExecutionRequest,
  V2VideoProjectExecutionResult,
  V2VideoProjectPreflight,
  V2VideoProjectSourceRequest,
} from "../types/video";
import axios from "axios";

export async function generateVideoProject(
  productId: number,
  payload: VideoProjectRequest,
): Promise<VideoProject> {
  const response = await apiClient.post<VideoProject>(
    `/products/${productId}/video-projects`,
    payload,
  );
  return response.data;
}

export async function preflightV2VideoProject(
  productId: number,
  payload: V2VideoProjectSourceRequest,
  signal?: AbortSignal,
): Promise<V2VideoProjectPreflight> {
  const response = await apiClient.post<V2VideoProjectPreflight>(
    `/products/${productId}/v2-video-project/preflight`,
    payload,
    { signal },
  );
  return response.data;
}

export async function executeV2VideoProject(
  productId: number,
  payload: V2VideoProjectExecutionRequest,
  signal?: AbortSignal,
): Promise<V2VideoProjectExecutionResult> {
  const response = await apiClient.post<V2VideoProjectExecutionResult>(
    `/products/${productId}/v2-video-project`,
    payload,
    { signal, timeout: AI_EXECUTION_TIMEOUT_MS },
  );
  return response.data;
}

export async function getLatestVideoProjectForProduct(
  productId: number,
  signal?: AbortSignal,
): Promise<VideoProject> {
  const response = await apiClient.get<VideoProject>(
    `/products/${productId}/video-projects/latest`,
    { signal },
  );
  return response.data;
}

export async function getVideoProject(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoProject> {
  const response = await apiClient.get<VideoProject>(
    `/video-projects/${videoProjectId}`,
    { signal },
  );
  return response.data;
}

export async function getVideoRenderPreflight(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoRenderPreflight> {
  const response = await apiClient.get<VideoRenderPreflight>(
    `/video-projects/${videoProjectId}/render-preflight`,
    { signal },
  );
  return response.data;
}

export function isVideoProjectNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

export function isVideoRenderTaskNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

export async function executeVideoProjectRender(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoRenderOperation> {
  const response = await apiClient.post<VideoRenderOperation>(
    `/video-projects/${videoProjectId}/render-execution`,
    undefined,
    { signal, timeout: AI_EXECUTION_TIMEOUT_MS },
  );
  return response.data;
}

export async function getLatestVideoRenderTask(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoRenderOperation> {
  const response = await apiClient.get<VideoRenderOperation>(
    `/video-projects/${videoProjectId}/render-tasks/latest`,
    { signal },
  );
  return response.data;
}

export async function recoverVideoRenderTask(
  taskId: number,
  signal?: AbortSignal,
): Promise<VideoRenderOperation> {
  const response = await apiClient.get<VideoRenderOperation>(
    `/video-render-tasks/${taskId}/recovery`,
    { signal },
  );
  return response.data;
}

export async function refreshWorkspaceVideoRenderTask(
  taskId: number,
  signal?: AbortSignal,
): Promise<VideoRenderOperation> {
  await apiClient.post(
    `/video-render-tasks/${taskId}/refresh`,
    undefined,
    { signal },
  );
  return recoverVideoRenderTask(taskId, signal);
}

export async function getVideoRenderArtifactMetadata(
  artifactId: number,
  signal?: AbortSignal,
): Promise<VideoRenderArtifactSafe> {
  const response = await apiClient.get<VideoRenderArtifactSafe>(
    `/video-render-artifacts/${artifactId}`,
    { signal },
  );
  return response.data;
}

export function getVideoRenderArtifactContentUrl(artifactId: number): string {
  const baseUrl = apiClient.defaults.baseURL?.replace(/\/$/, "") ?? "";
  return `${baseUrl}/video-render-artifacts/${artifactId}/content`;
}

export async function downloadVideoRenderArtifact(
  artifactId: number,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await apiClient.get<Blob>(
    `/video-render-artifacts/${artifactId}/download`,
    { responseType: "blob", signal },
  );
  return response.data;
}

export async function getVideoRenderArtifacts(
  videoProjectId: number,
): Promise<VideoRenderArtifact[]> {
  if (
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("mode") ===
      "presentation"
  ) {
    return [];
  }
  const response = await apiClient.get<VideoRenderArtifact[]>(
    `/video-projects/${videoProjectId}/render-artifacts`,
  );
  return response.data;
}

export async function createLiveVideoRender(
  videoProjectId: number,
): Promise<LiveRenderTaskResponse> {
  const response = await apiClient.post<LiveRenderTaskResponse>(
    `/video-projects/${videoProjectId}/live-render`,
    { confirm_live_generation: true },
  );
  return response.data;
}

export async function refreshVideoRenderTask(
  taskId: number,
): Promise<LiveRenderTaskResponse> {
  const response = await apiClient.post<LiveRenderTaskResponse>(
    `/video-render-tasks/${taskId}/refresh`,
  );
  return response.data;
}
