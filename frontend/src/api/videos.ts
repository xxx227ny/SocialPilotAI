import { apiClient } from "./client";
import type { VideoProject, VideoProjectRequest } from "../types/video";

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
