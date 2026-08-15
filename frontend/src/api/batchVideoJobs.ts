import { apiClient } from "./client";
import type {
  BatchProductOption,
  BatchVideoCreateResult,
  BatchVideoJob,
  BatchVideoPreflight,
  BatchVideoRequest,
  BatchVideoVariant,
} from "../types/batchVideo";

export async function listBatchProducts(signal?: AbortSignal) {
  const response = await apiClient.get<BatchProductOption[]>("/products", { signal });
  return response.data;
}

export async function preflightBatchVideo(data: BatchVideoRequest, signal?: AbortSignal) {
  const response = await apiClient.post<BatchVideoPreflight>(
    "/batch-video-jobs/preflight",
    data,
    { signal },
  );
  return response.data;
}

export async function createBatchVideo(
  data: BatchVideoRequest,
  preflight: BatchVideoPreflight,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<BatchVideoCreateResult>(
    "/batch-video-jobs",
    {
      ...data,
      request_digest: preflight.request_digest,
      preflight_digest: preflight.preflight_digest,
      preflight_expires_at: preflight.expires_at,
      cost_confirmed: true,
    },
    { signal },
  );
  return response.data;
}

export async function getBatchVideoJob(batchId: number, signal?: AbortSignal) {
  const response = await apiClient.get<BatchVideoJob>(`/batch-video-jobs/${batchId}`, { signal });
  return response.data;
}

export async function listBatchVideoVariants(batchId: number, signal?: AbortSignal) {
  const response = await apiClient.get<BatchVideoVariant[]>(
    `/batch-video-jobs/${batchId}/variants`,
    { signal },
  );
  return response.data;
}

export async function controlBatchVideoJob(
  batchId: number,
  action: "pause" | "resume" | "cancel",
  signal?: AbortSignal,
) {
  const response = await apiClient.post<BatchVideoJob>(
    `/batch-video-jobs/${batchId}/${action}`,
    undefined,
    { signal },
  );
  return response.data;
}
