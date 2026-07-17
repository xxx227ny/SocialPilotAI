export interface ProductAsset {
  id: number;
  product_id: number;
  file_name: string;
  file_path: string;
  file_type: string;
  created_at: string;
}

export interface Product {
  id: number;
  name: string;
  category: string | null;
  description: string | null;
  selling_points: string[];
  target_markets: string[];
  created_at: string;
  updated_at: string;
  assets: ProductAsset[];
}

export interface ProductCreatePayload {
  name: string;
  category: string;
  description: string;
  selling_points: string[];
  target_markets: string[];
}
