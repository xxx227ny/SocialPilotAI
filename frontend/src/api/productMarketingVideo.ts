import { apiClient } from "./client";
import type { ExecutionJob } from "../types/execution";
import type {
  HappyHorseVideoPreflight,
  MarketingJobResult,
  ProductVideoPrepare,
  ProductVideoSource,
  UploadedProductImage,
} from "../types/productMarketingVideo";

export async function listProductVideoSources(productId: number, signal?: AbortSignal) {
  const response = await apiClient.get<ProductVideoSource[]>(
    `/products/${productId}/real-product-video/sources`,
    { signal },
  );
  return response.data;
}

export async function prepareProductVideo(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ProductVideoPrepare>(
    `/products/${productId}/real-product-video/prepare`,
    payload,
    { signal },
  );
  return response.data;
}

export async function submitProductImageJob(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<MarketingJobResult>(
    `/products/${productId}/real-product-video/image-jobs`,
    payload,
    { signal },
  );
  return response.data;
}

export async function submitWanxProductImageJob(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<MarketingJobResult>(
    `/products/${productId}/real-product-video/wanx-image-jobs`,
    payload,
    { signal },
  );
  return response.data;
}

export async function getProductImageAsset(
  productId: number,
  assetId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<UploadedProductImage>(
    `/products/${productId}/image-assets/${assetId}`,
    { signal },
  );
  return response.data;
}

export async function submitVoiceoverJob(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<MarketingJobResult>(
    `/products/${productId}/real-product-video/voiceover-jobs`,
    payload,
    { signal },
  );
  return response.data;
}

export async function preflightHappyHorseVideo(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<HappyHorseVideoPreflight>(
    `/products/${productId}/real-product-video/happyhorse-preflight`,
    payload,
    { signal },
  );
  return response.data;
}

export async function submitHappyHorseVideo(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<MarketingJobResult>(
    `/products/${productId}/real-product-video/happyhorse-jobs`,
    payload,
    { signal },
  );
  return response.data;
}

export async function refreshHappyHorseVideo(
  productId: number,
  taskId: number,
  videoProjectId: number,
  refreshRequestId: string,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<MarketingJobResult>(
    `/products/${productId}/real-product-video/happyhorse-tasks/${taskId}/refresh-jobs`,
    {
      video_project_id: videoProjectId,
      refresh_request_id: refreshRequestId,
    },
    { signal },
  );
  return response.data;
}

export const happyHorseVideoContentUrl = (artifactId: number) =>
  `/api/v1/video-render-artifacts/${artifactId}/content`;

export async function getExactMarketingJob(jobId: number, signal?: AbortSignal) {
  const response = await apiClient.get<ExecutionJob>(`/execution-jobs/${jobId}`, {
    signal,
  });
  return response.data;
}
