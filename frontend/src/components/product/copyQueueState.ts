import type { ExecutionJob } from "../../types/execution";
import type { PersistedCopyMatrix, PlatformCopy } from "../../types/copy";

export const QWEN_COPY_MATRIX_JOB_TYPE = "qwen.copy_matrix.generate.v1";

export function selectExactCopyJob(
  jobs: ExecutionJob[],
  taskId: number,
  productId: number,
  strategyId: number,
  inputDigest: string,
): ExecutionJob | null {
  return jobs
    .filter(
      (job) =>
        job.job_type === QWEN_COPY_MATRIX_JOB_TYPE &&
        job.source_type === "marketing_strategy" &&
        job.source_id === strategyId &&
        job.input_digest === inputDigest &&
        job.input_payload.product_id === productId &&
        job.input_payload.marketing_brief_id === taskId &&
        job.input_payload.marketing_strategy_id === strategyId &&
        job.input_payload.frozen_digest === inputDigest,
    )
    .reduce<ExecutionJob | null>(
      (latest, candidate) =>
        latest === null || candidate.id > latest.id ? candidate : latest,
      null,
    );
}

export function platformCopyText(copy: PlatformCopy): string {
  return [
    copy.platform,
    `开场钩子：${copy.hook}`,
    `正文：${copy.caption}`,
    `话题标签：${copy.hashtags.join(" ")}`,
    `行动号召：${copy.cta}`,
  ].join("\n");
}

export function copyMatrixText(matrix: PersistedCopyMatrix): string {
  return matrix.copies.map(platformCopyText).join("\n\n---\n\n");
}

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

export function copyMatrixCsv(matrix: PersistedCopyMatrix): string {
  const rows = [
    ["平台", "开场钩子", "正文", "话题标签", "行动号召"],
    ...matrix.copies.map((copy) => [
      copy.platform,
      copy.hook,
      copy.caption,
      copy.hashtags.join(" "),
      copy.cta,
    ]),
  ];
  return `\uFEFF${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
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
