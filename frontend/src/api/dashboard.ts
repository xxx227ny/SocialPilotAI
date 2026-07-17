import { apiClient } from "./client";
import type { DashboardSnapshot } from "../types/dashboard";

export async function prepareDemo(): Promise<DashboardSnapshot> {
  const response = await apiClient.post<DashboardSnapshot>("/demo/prepare");
  return response.data;
}

export async function getDemoSnapshot(): Promise<DashboardSnapshot> {
  const response = await apiClient.get<DashboardSnapshot>("/demo/snapshot");
  return response.data;
}

export async function getProductDashboard(
  productId: number,
): Promise<DashboardSnapshot> {
  const response = await apiClient.get<DashboardSnapshot>(
    `/dashboard/products/${productId}`,
  );
  return response.data;
}
