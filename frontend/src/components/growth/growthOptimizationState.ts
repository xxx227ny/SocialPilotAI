import type {
  FeedbackContext,
  GrowthAnalysis,
  GrowthAutomationControl,
  GrowthOptimizationExecution,
  GrowthOptimizationExecutionPreflight,
  GrowthOptimizationPolicy,
  GrowthOptimizationRun,
} from "../../types/growth";

export function analysisMatchesContext(
  analysis: GrowthAnalysis | null,
  context: FeedbackContext,
): boolean {
  return Boolean(
    analysis &&
      analysis.product_id === context.product_id &&
      analysis.source_context_digest === context.context_digest,
  );
}

export function optimizationIdempotencyKey(
  analysis: GrowthAnalysis,
  policy: GrowthOptimizationPolicy,
): string {
  const values = [
    policy.total_budget,
    policy.target_roas,
    policy.minimum_platform_share,
    policy.performance_tilt_share,
    policy.maximum_bid_adjustment_pct,
  ].map((value) => Number(value).toString());
  return `growth:${analysis.recommendation_digest.slice(0, 32)}:${values.join(":")}`;
}

export function mergeOptimizationRun(
  runs: GrowthOptimizationRun[],
  incoming: GrowthOptimizationRun,
): GrowthOptimizationRun[] {
  return [...runs.filter((item) => item.id !== incoming.id), incoming].sort(
    (left, right) => left.id - right.id,
  );
}

export function activeOptimizationRun(
  runs: GrowthOptimizationRun[],
): GrowthOptimizationRun | null {
  return runs.find((item) => item.status === "ACTIVE") ?? null;
}

export function canCreateOptimizationRun(
  analysis: GrowthAnalysis | null,
  context: FeedbackContext,
  policy: GrowthOptimizationPolicy,
  busy: boolean,
): boolean {
  return Boolean(
    !busy &&
      context.context_ready &&
      analysisMatchesContext(analysis, context) &&
      policy.total_budget > 0 &&
      policy.target_roas > 0,
  );
}

export function sandboxExecutionIdempotencyKey(
  run: GrowthOptimizationRun,
  contextDigest: string,
  executionCount: number,
): string {
  return `growth-sandbox:${run.id}:${contextDigest.slice(0, 32)}:${executionCount + 1}`;
}

export function canPreflightSandboxExecution(
  run: GrowthOptimizationRun | null,
  context: FeedbackContext,
  busy: boolean,
): boolean {
  return Boolean(
    !busy &&
      run?.status === "ACTIVE" &&
      run.product_id === context.product_id &&
      run.source_context_digest === context.context_digest,
  );
}

export function canExecuteSandbox(
  preflight: GrowthOptimizationExecutionPreflight | null,
  confirmed: boolean,
  busy: boolean,
): boolean {
  return Boolean(!busy && confirmed && preflight?.ready);
}

export function mergeOptimizationExecution(
  executions: GrowthOptimizationExecution[],
  incoming: GrowthOptimizationExecution,
): GrowthOptimizationExecution[] {
  return [
    ...executions.filter((item) => item.id !== incoming.id),
    incoming,
  ].sort((left, right) => left.id - right.id);
}

export function canEvaluateAutomation(
  control: GrowthAutomationControl | null,
  run: GrowthOptimizationRun | null,
  context: FeedbackContext,
  busy: boolean,
): boolean {
  return Boolean(
    !busy &&
      control?.mode === "AUTO_SANDBOX" &&
      !control.kill_switch_engaged &&
      run?.status === "ACTIVE" &&
      run.source_context_digest === context.context_digest,
  );
}

export function automationEvaluationIdempotencyKey(
  run: GrowthOptimizationRun,
  contextDigest: string,
  executionCount: number,
): string {
  return `growth-auto:${run.id}:${contextDigest.slice(0, 32)}:${executionCount + 1}`;
}
