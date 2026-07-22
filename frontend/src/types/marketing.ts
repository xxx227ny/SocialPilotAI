export type MarketingPlatform = "TikTok" | "Instagram" | "Facebook";

export interface MarketingTaskCreatePayload {
  product_id: number;
  audience: string;
  language: string;
  platforms: MarketingPlatform[];
  tone: string;
  objective: string;
}

export interface MarketingTask extends MarketingTaskCreatePayload {
  id: number;
  target_markets: string[];
  created_at: string;
}
