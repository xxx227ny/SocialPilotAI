import { AI_EXECUTION_TIMEOUT_MS, apiClient, apiContentUrl } from "./client";
import type { ExecutionJob } from "../types/execution";
import type {
  HappyHorseVideoPreflight,
  MarketingJobResult,
  ProductVideoPrepare,
  ProductVideoProductionResult,
  ProductVideoSource,
  ThreePlatformVideoPreflight,
  UploadedProductImage,
} from "../types/productMarketingVideo";

export async function listProductVideoSources(productId: number, signal?: AbortSignal) {
  const response = await apiClient.get<ProductVideoSource[]>(
    `/products/${productId}/real-product-video/sources`,
    { signal },
  );
  return response.data;
}

export async function preflightThreePlatformVideo(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ThreePlatformVideoPreflight>(
    `/products/${productId}/real-product-video/three-platform-preflight`,
    payload,
    { signal },
  );
  return response.data;
}

export async function createProductVideoProductionBatch(
  productId: number,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ProductVideoProductionResult>(
    `/products/${productId}/real-product-video/production-batches`,
    payload,
    { signal },
  );
  return response.data;
}

export async function getProductVideoProductionBatch(
  productId: number,
  batchId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<ProductVideoProductionResult>(
    `/products/${productId}/real-product-video/production-batches/${batchId}`,
    { signal },
  );
  return response.data;
}

export const productVideoProductionBatchDownloadUrl = (
  productId: number,
  batchId: number,
) =>
  apiContentUrl(
    `/products/${productId}/real-product-video/production-batches/${batchId}/download`,
  );

async function controlProductVideoProductionBatch(
  productId: number,
  batchId: number,
  action: "advance" | "pause" | "resume" | "cancel",
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ProductVideoProductionResult>(
    `/products/${productId}/real-product-video/production-batches/${batchId}/${action}`,
    undefined,
    {
      signal,
      timeout: action === "advance" ? AI_EXECUTION_TIMEOUT_MS : undefined,
    },
  );
  return response.data;
}

export const advanceProductVideoProductionBatch = (
  productId: number,
  batchId: number,
  signal?: AbortSignal,
) => controlProductVideoProductionBatch(productId, batchId, "advance", signal);

export const pauseProductVideoProductionBatch = (
  productId: number,
  batchId: number,
  signal?: AbortSignal,
) => controlProductVideoProductionBatch(productId, batchId, "pause", signal);

export const resumeProductVideoProductionBatch = (
  productId: number,
  batchId: number,
  confirmUncertainVoiceoverReplacement = false,
  signal?: AbortSignal,
) =>
  apiClient
    .post<ProductVideoProductionResult>(
      `/products/${productId}/real-product-video/production-batches/${batchId}/resume`,
      confirmUncertainVoiceoverReplacement
        ? { confirm_uncertain_voiceover_replacement: true }
        : undefined,
      { signal },
    )
    .then((response) => response.data);

export const cancelProductVideoProductionBatch = (
  productId: number,
  batchId: number,
  signal?: AbortSignal,
) => controlProductVideoProductionBatch(productId, batchId, "cancel", signal);

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
  apiContentUrl(`/video-render-artifacts/${artifactId}/content`);
export const happyHorseVideoPreviewUrl = (artifactId: number) =>
  apiContentUrl(`/video-render-artifacts/${artifactId}/preview`);

export async function getExactMarketingJob(jobId: number, signal?: AbortSignal) {
  const response = await apiClient.get<ExecutionJob>(`/execution-jobs/${jobId}`, {
    signal,
  });
  return response.data;
}
