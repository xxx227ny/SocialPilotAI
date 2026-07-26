function isEnabledFeatureFlag(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

export const strategyExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_STRATEGY_EXECUTION,
);

export const copyExecutionEnabled = isEnabledFeatureFlag(
  import.meta.env.VITE_ENABLE_COPY_EXECUTION,
);
