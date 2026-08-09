import type {
  BrandKit,
  BrandKitCreatePayload,
  BrandKitVersionCreateResult,
  BrandKitVersionInput,
  ProductBrandKitBindingPayload,
} from "../types/brandKit";
import type { Product } from "../types/product";
import { apiClient } from "./client";

export async function listBrandKits(signal?: AbortSignal): Promise<BrandKit[]> {
  const response = await apiClient.get<BrandKit[]>("/brand-kits", { signal });
  return response.data;
}

export async function createBrandKit(
  payload: BrandKitCreatePayload,
): Promise<BrandKit> {
  const response = await apiClient.post<BrandKit>("/brand-kits", payload);
  return response.data;
}

export async function createBrandKitVersion(
  brandKitId: number,
  payload: BrandKitVersionInput,
): Promise<BrandKitVersionCreateResult> {
  const response = await apiClient.post<BrandKitVersionCreateResult>(
    `/brand-kits/${brandKitId}/versions`,
    payload,
  );
  return response.data;
}

export async function bindProductBrandKitVersion(
  productId: number,
  payload: ProductBrandKitBindingPayload,
): Promise<Product> {
  const response = await apiClient.put<Product>(
    `/products/${productId}/brand-kit-version`,
    payload,
  );
  return response.data;
}

export async function unbindProductBrandKitVersion(
  productId: number,
): Promise<Product> {
  const response = await apiClient.delete<Product>(
    `/products/${productId}/brand-kit-version`,
  );
  return response.data;
}
