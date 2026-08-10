import type { ExecutionJob } from "../../types/execution";

export const QWEN_STRATEGY_JOB_TYPE = "qwen.strategy.generate.v1";

export function selectExactStrategyJob(
  jobs: ExecutionJob[],
  taskId: number,
  productId: number,
  inputDigest: string,
): ExecutionJob | null {
  return (
    jobs.find(
      (job) =>
        job.job_type === QWEN_STRATEGY_JOB_TYPE &&
        job.source_type === "marketing_brief" &&
        job.source_id === taskId &&
        job.input_digest === inputDigest &&
        job.input_payload.product_id === productId &&
        job.input_payload.marketing_brief_id === taskId &&
        job.input_payload.frozen_digest === inputDigest,
    ) ?? null
  );
}

export function jobNeedsPolling(job: ExecutionJob | null): boolean {
  return job?.status === "QUEUED" || job?.status === "RUNNING";
}

export function jobAllowsExplicitRetry(job: ExecutionJob | null): boolean {
  return Boolean(
    job?.status === "FAILED" &&
      !job.uncertain &&
      job.attempt_count < job.max_attempts,
  );
}

export function exactStrategyResultId(job: ExecutionJob | null): number | null {
  if (
    job?.status !== "SUCCEEDED" ||
    job.result_entity_type !== "marketing_strategy" ||
    job.result_entity_id === null
  ) {
    return null;
  }
  return job.result_entity_id;
}
