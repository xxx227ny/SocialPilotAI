import { apiClient } from "./client";
import type {
    CampaignUploadResponse,
  FeedbackContext,
} from "../types/growth";

export async function uploadCampaignCsv(
  productId: number,
  file: File,
  signal?: AbortSignal,
): Promise<CampaignUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<CampaignUploadResponse>(
    `/products/${productId}/campaigns/upload`,
    formData,
    { signal },
  );
  return response.data;
}

export async function getFeedbackContext(
  productId: number,
  signal?: AbortSignal,
): Promise<FeedbackContext> {
  const response = await apiClient.get<FeedbackContext>(
    `/products/${productId}/feedback-context`,
    { signal },
  );
  return response.data;
}
