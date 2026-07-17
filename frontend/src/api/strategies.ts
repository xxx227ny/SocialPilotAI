import type { MarketingStrategy } from "../types/strategy";
import { apiClient } from "./client";

export async function generateMarketingStrategy(
  productId: number,
): Promise<MarketingStrategy> {
  const response = await apiClient.post<MarketingStrategy>(
    `/products/${productId}/strategy`,
  );
  return response.data;
}
