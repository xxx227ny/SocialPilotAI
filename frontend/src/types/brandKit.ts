export interface BrandKitVersionInput {
  brand_name: string;
  positioning: string;
  default_language: string;
  brand_tone: string;
  preferred_terms: string[];
  forbidden_terms: string[];
  target_regions: string[];
  audience_guidelines: string[];
  visual_guidelines: string[];
  required_disclosures: string[];
  claims_constraints: string[];
}

export interface BrandKitVersion extends BrandKitVersionInput {
  id: number;
  brand_kit_id: number;
  version_number: number;
  digest: string;
  created_at: string;
}

export interface BrandKit {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
  versions: BrandKitVersion[];
}

export interface BrandKitCreatePayload {
  name: string;
  version: BrandKitVersionInput;
}

export interface BrandKitVersionCreateResult {
  version: BrandKitVersion;
  reused: boolean;
}

export interface ProductBrandKitBindingPayload {
  brand_kit_id: number;
  brand_kit_version_id: number;
}
