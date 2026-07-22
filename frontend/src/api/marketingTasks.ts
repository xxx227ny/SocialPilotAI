import type {
  MarketingTask,
  MarketingTaskCreatePayload,
} from "../types/marketing";
import { apiClient } from "./client";

export async function createMarketingTask(
  payload: MarketingTaskCreatePayload,
  signal?: AbortSignal,
): Promise<MarketingTask> {
  const response = await apiClient.post<MarketingTask>(
    "/marketing-tasks",
    payload,
    { signal },
  );
  return response.data;
}

export async function getMarketingTask(
  taskId: number,
  signal?: AbortSignal,
): Promise<MarketingTask> {
  const response = await apiClient.get<MarketingTask>(
    `/marketing-tasks/${taskId}`,
    { signal },
  );
  return response.data;
}

export async function getLatestMarketingTask(
  productId: number,
  signal?: AbortSignal,
): Promise<MarketingTask | null> {
  const response = await apiClient.get<MarketingTask | null>(
    "/marketing-tasks/latest",
    { params: { product_id: productId }, signal },
  );
  return response.data;
}
