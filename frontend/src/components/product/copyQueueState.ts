import type { ExecutionJob } from "../../types/execution";

export const QWEN_COPY_MATRIX_JOB_TYPE = "qwen.copy_matrix.generate.v1";

export function selectExactCopyJob(
  jobs: ExecutionJob[],
  taskId: number,
  productId: number,
  strategyId: number,
  inputDigest: string,
): ExecutionJob | null {
  return (
    jobs.find(
      (job) =>
        job.job_type === QWEN_COPY_MATRIX_JOB_TYPE &&
        job.source_type === "marketing_strategy" &&
        job.source_id === strategyId &&
        job.input_digest === inputDigest &&
        job.input_payload.product_id === productId &&
        job.input_payload.marketing_brief_id === taskId &&
        job.input_payload.marketing_strategy_id === strategyId &&
        job.input_payload.frozen_digest === inputDigest,
    ) ?? null
  );
}

export function copyJobNeedsPolling(job: ExecutionJob | null): boolean {
  return job?.status === "QUEUED" || job?.status === "RUNNING";
}

export function copyJobAllowsExplicitRetry(
  job: ExecutionJob | null,
): boolean {
  return Boolean(
    job?.status === "FAILED" &&
      !job.uncertain &&
      job.attempt_count < job.max_attempts,
  );
}

export function exactCopyResultId(job: ExecutionJob | null): number | null {
  if (
    job?.status !== "SUCCEEDED" ||
    job.result_entity_type !== "copy_matrix" ||
    job.result_entity_id === null
  ) {
    return null;
  }
  return job.result_entity_id;
}
