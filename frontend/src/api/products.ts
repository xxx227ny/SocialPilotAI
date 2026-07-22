import type { Product, ProductCreatePayload } from "../types/product";
import { apiClient } from "./client";

export async function listProducts(): Promise<Product[]> {
  const response = await apiClient.get<Product[]>("/products");
  return response.data;
}

export async function getProduct(
  productId: number,
  signal?: AbortSignal,
): Promise<Product> {
  const response = await apiClient.get<Product>(`/products/${productId}`, {
    signal,
  });
  return response.data;
}

export async function createProduct(
  payload: ProductCreatePayload,
): Promise<Product> {
  const response = await apiClient.post<Product>("/products", payload);
  return response.data;
}
