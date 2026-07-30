function isEnabledFeatureFlag(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

export const strategyExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_STRATEGY_EXECUTION,
);

export const copyExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_COPY_EXECUTION,
);

export const v2CopyExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_V2_COPY_EXECUTION,
);

export const videoRenderExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_VIDEO_RENDER_EXECUTION,
);

export const growthExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_GROWTH_EXECUTION,
);
