export interface VideoProjectRequest {
  platform: string;
  duration_seconds: number;
  aspect_ratio: string;
}

export interface VideoScene {
  sequence: number;
  duration_seconds: number;
  shot_type: string;
  visual_description: string;
  action: string;
  narration: string;
}

export interface VideoProject extends VideoProjectRequest {
  id: number;
  product_id: number;
  marketing_strategy_id: number;
  copy_matrix_id: number;
  title: string;
  concept: string;
  scenes: VideoScene[];
  cta: string;
  status: string;
  created_at: string;
  updated_at: string;
}
