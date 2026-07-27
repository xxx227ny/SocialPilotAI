import { apiClient } from "./client";
import type {
  LiveRenderTaskResponse,
  VideoProject,
  VideoProjectRequest,
  VideoRenderArtifact,
  VideoRenderArtifactSafe,
  VideoRenderOperation,
  VideoRenderPreflight,
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
    { signal },
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

export async function getVideoRenderArtifacts(
  videoProjectId: number,
): Promise<VideoRenderArtifact[]> {
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
