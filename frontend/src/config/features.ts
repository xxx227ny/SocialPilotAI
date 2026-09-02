export function isEnabledFeatureFlag(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

// Strategy generation is part of the product's supported production flow.
// The backend still enforces workspace credentials, preflight validation and
// explicit cost confirmation before any provider call can be queued.
export const strategyExecutionEnabled = import.meta.env.PROD || isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_STRATEGY_EXECUTION,
);

// Copy generation is the next supported step after a production strategy job.
// Provider credentials, frozen inputs and cost confirmation remain enforced by
// the backend before the user's own Qwen key can be used.
export const copyExecutionEnabled = import.meta.env.PROD || isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_COPY_EXECUTION,
);

export const v2CopyExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_V2_COPY_EXECUTION,
);

export const videoProjectExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_VIDEO_PROJECT_EXECUTION,
);

export const v2VideoProjectExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_V2_VIDEO_PROJECT_EXECUTION,
);

export const videoRenderExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_VIDEO_RENDER_EXECUTION,
);

export const videoCompositionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_VIDEO_COMPOSITION,
);

export const videoCompositionEnhancementEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_VIDEO_COMPOSITION_ENHANCEMENT,
);

// Batch orchestration is a supported production workspace section. It stays
// hidden in presentation mode and its backend preflight still prevents any
// unconfirmed provider work.
export const batchVideoJobsEnabled = import.meta.env.PROD || isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_BATCH_VIDEO_JOBS,
);
export const videoScriptVersionsEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_VIDEO_SCRIPT_VERSIONS,
);
export const qwenVideoScriptGenerationEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_QWEN_VIDEO_SCRIPT_GENERATION,
);
export const realProductVideoEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_REAL_PRODUCT_VIDEO,
);

export const growthExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_GROWTH_EXECUTION,
);

export const socialAccountBindingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_SOCIAL_ACCOUNT_BINDING,
);

export const instagramAccountBindingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_INSTAGRAM_ACCOUNT_BINDING,
);

export const tiktokAccountBindingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_TIKTOK_ACCOUNT_BINDING,
);

export const pinterestAccountBindingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_PINTEREST_ACCOUNT_BINDING,
);

export const youtubePublishingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_YOUTUBE_PUBLISHING,
);

export const instagramPublishingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_INSTAGRAM_PUBLISHING,
);

export const tiktokPublishingEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_TIKTOK_PUBLISHING,
);
