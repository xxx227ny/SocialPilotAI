export interface PlatformCopy {
  platform: "TikTok" | "Instagram" | "Facebook";
  hook: string;
  caption: string;
  hashtags: string[];
  cta: string;
}

export interface CopyMatrix {
  product_id: number;
  copies: PlatformCopy[];
}
