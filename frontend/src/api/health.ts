import type { HealthResponse, SystemReadinessResponse } from "../types/health";
import { apiClient } from "./client";

export async function getHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>("/health");
  return response.data;
}

export async function getSystemReadiness(
  signal?: AbortSignal,
): Promise<SystemReadinessResponse> {
  const response = await apiClient.get<SystemReadinessResponse>(
    "/system/readiness",
    { signal },
  );
  return response.data;
}
