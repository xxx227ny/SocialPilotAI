import { apiClient } from "./client";
import type {
  CampaignUploadResponse,
  GrowthAnalysis,
} from "../types/growth";

export async function uploadCampaignCsv(
  productId: number,
  file: File,
): Promise<CampaignUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<CampaignUploadResponse>(
    `/products/${productId}/campaigns/upload`,
    formData,
  );
  return response.data;
}

export async function generateGrowthAnalysis(
  productId: number,
): Promise<GrowthAnalysis> {
  const response = await apiClient.post<GrowthAnalysis>(
    `/products/${productId}/growth-analysis`,
  );
  return response.data;
}
