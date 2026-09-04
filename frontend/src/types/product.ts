export interface ProductAsset {
  id: number;
  product_id: number;
  file_name: string;
  file_path: string;
  file_type: string;
  content_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  width: number | null;
  height: number | null;
  created_at: string;
}

export interface Product {
  id: number;
  display_number: number | null;
  brand_kit_version_id: number | null;
  name: string;
  category: string | null;
  description: string | null;
  selling_points: string[];
  target_markets: string[];
  created_at: string;
  updated_at: string;
  assets: ProductAsset[];
}

export function productDisplayNumber(
  product: Pick<Product, "id" | "display_number">,
): number {
  return product.display_number ?? product.id;
}

export interface ProductCreatePayload {
  name: string;
  category: string;
  description: string;
  selling_points: string[];
}

export interface ProductUpdatePayload {
  target_markets?: string[];
}
