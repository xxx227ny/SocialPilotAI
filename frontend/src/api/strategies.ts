import type {
  MarketingStrategy,
  StrategyPreflight,
} from "../types/strategy";
import { apiClient } from "./client";

export async function generateMarketingStrategy(
  productId: number,
): Promise<MarketingStrategy> {
  const response = await apiClient.post<MarketingStrategy>(
    `/products/${productId}/strategy`,
  );
  return response.data;
}

export async function getStrategyPreflight(
  taskId: number,
  signal?: AbortSignal,
): Promise<StrategyPreflight> {
  const response = await apiClient.get<StrategyPreflight>(
    `/marketing-tasks/${taskId}/strategy-preflight`,
    { signal },
  );
  return response.data;
}
