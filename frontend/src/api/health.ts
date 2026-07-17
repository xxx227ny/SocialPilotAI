import type { HealthResponse } from "../types/health";
import { apiClient } from "./client";

export async function getHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>("/health");
  return response.data;
}
