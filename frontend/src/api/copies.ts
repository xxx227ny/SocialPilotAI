import type { CopyMatrix, CopyPreflight } from "../types/copy";
import { apiClient } from "./client";

export async function generateCopyMatrix(productId: number): Promise<CopyMatrix> {
  const response = await apiClient.post<CopyMatrix>(`/products/${productId}/copy`);
  return response.data;
}

export async function getCopyPreflight(
  taskId: number,
  strategyId: number,
  signal?: AbortSignal,
): Promise<CopyPreflight> {
  const response = await apiClient.get<CopyPreflight>(
    `/marketing-tasks/${taskId}/strategies/${strategyId}/copy-preflight`,
    { signal },
  );
  return response.data;
}
