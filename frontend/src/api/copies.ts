import type { CopyMatrix } from "../types/copy";
import { apiClient } from "./client";

export async function generateCopyMatrix(productId: number): Promise<CopyMatrix> {
  const response = await apiClient.post<CopyMatrix>(`/products/${productId}/copy`);
  return response.data;
}
