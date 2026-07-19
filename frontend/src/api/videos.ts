import { apiClient } from "./client";
import type {
  VideoProject,
  VideoProjectRequest,
  LiveRenderTaskResponse,
  VideoRenderArtifact,
} from "../types/video";

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
