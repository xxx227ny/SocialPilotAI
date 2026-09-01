import type {
  Product,
  ProductCreatePayload,
  ProductUpdatePayload,
} from "../types/product";
import type { UploadedProductImage } from "../types/productMarketingVideo";
import { apiClient, apiContentUrl } from "./client";

export async function listProducts(signal?: AbortSignal): Promise<Product[]> {
  const response = await apiClient.get<Product[]>("/products", { signal });
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

export async function updateProduct(
  productId: number,
  payload: ProductUpdatePayload,
): Promise<Product> {
  const response = await apiClient.patch<Product>(`/products/${productId}`, payload);
  return response.data;
}

export async function deleteProduct(
  productId: number,
  signal?: AbortSignal,
): Promise<void> {
  await apiClient.delete(`/products/${productId}`, { signal });
}

export async function deleteProductImage(
  productId: number,
  assetId: number,
  signal?: AbortSignal,
): Promise<void> {
  await apiClient.delete(`/products/${productId}/image-assets/${assetId}`, {
    signal,
  });
}

export async function uploadProductImage(
  productId: number,
  file: File,
  signal?: AbortSignal,
): Promise<UploadedProductImage> {
  const body = new FormData();
  body.append("file", file, file.name);
  const response = await apiClient.post<UploadedProductImage>(
    `/products/${productId}/image-assets`,
    body,
    { signal },
  );
  return response.data;
}

export function productImageContentUrl(
  productId: number,
  assetId: number,
): string {
  return apiContentUrl(`/products/${productId}/image-assets/${assetId}/content`);
}

export function productImageThumbnailUrl(productId: number, assetId: number): string {
  return apiContentUrl(`/products/${productId}/image-assets/${assetId}/thumbnail`);
}
