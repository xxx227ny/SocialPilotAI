import type { ExecutionJob } from "../../types/execution";
import type {
  InitialVideoProjectPreflight,
  InitialVideoProjectSource,
  InitialVideoProjectSourceRequest,
} from "../../types/video";

export const QWEN_VIDEO_PROJECT_JOB_TYPE =
  "qwen.video_project.generate.v1";

export function selectExactInitialVideoSource(
  productId: number,
  source: InitialVideoProjectSource,
): Pick<InitialVideoProjectSourceRequest, "strategy_id" | "copy_matrix_id"> | null {
  if (
    source.product_id !== productId ||
    source.strategy_id <= 0 ||
    source.copy_matrix_id <= 0
  ) {
    return null;
  }
  return {
    strategy_id: source.strategy_id,
    copy_matrix_id: source.copy_matrix_id,
  };
}

export function preflightMatchesInitialRequest(
  preflight: InitialVideoProjectPreflight | null,
  request: InitialVideoProjectSourceRequest | null,
): boolean {
  return Boolean(
    preflight &&
      request &&
      preflight.strategy_id === request.strategy_id &&
      preflight.copy_matrix_id === request.copy_matrix_id &&
      preflight.platform === request.platform &&
      preflight.duration_seconds === request.duration_seconds &&
      preflight.aspect_ratio === request.aspect_ratio,
  );
}

export function selectExactInitialVideoProjectJob(
  jobs: ExecutionJob[],
  productId: number,
  request: InitialVideoProjectSourceRequest,
  inputDigest: string,
): ExecutionJob | null {
  return (
    jobs.find(
      (job) =>
        job.job_type === QWEN_VIDEO_PROJECT_JOB_TYPE &&
        job.source_type === "product" &&
        job.source_id === productId &&
        job.input_digest === inputDigest &&
        job.input_payload.product_id === productId &&
        job.input_payload.marketing_strategy_id === request.strategy_id &&
        job.input_payload.copy_matrix_id === request.copy_matrix_id &&
        job.input_payload.platform === request.platform &&
        job.input_payload.duration_seconds === request.duration_seconds &&
        job.input_payload.aspect_ratio === request.aspect_ratio &&
        job.input_payload.frozen_input_digest === inputDigest,
    ) ?? null
  );
}

export function canEnqueueInitialVideoProject({
  frontendGateEnabled,
  preflight,
  request,
  costConfirmed,
  submitLocked,
  job,
  now = Date.now(),
}: {
  frontendGateEnabled: boolean;
  preflight: InitialVideoProjectPreflight | null;
  request: InitialVideoProjectSourceRequest | null;
  costConfirmed: boolean;
  submitLocked: boolean;
  job: ExecutionJob | null;
  now?: number;
}): boolean {
  return Boolean(
    frontendGateEnabled &&
      preflight?.ready_for_execution &&
      preflightMatchesInitialRequest(preflight, request) &&
      Date.parse(preflight.expires_at) > now &&
      costConfirmed &&
      !submitLocked &&
      job === null,
  );
}

export function initialVideoProjectJobNeedsPolling(
  job: ExecutionJob | null,
): boolean {
  return job?.status === "QUEUED" || job?.status === "RUNNING";
}

export function initialVideoProjectJobAllowsExplicitRetry(
  job: ExecutionJob | null,
): boolean {
  return Boolean(
    job?.status === "FAILED" &&
      !job.uncertain &&
      job.attempt_count < job.max_attempts,
  );
}

export function exactInitialVideoProjectResultId(
  job: ExecutionJob | null,
): number | null {
  if (
    job?.status !== "SUCCEEDED" ||
    job.result_entity_type !== "video_project" ||
    job.result_entity_id === null
  ) {
    return null;
  }
  return job.result_entity_id;
}
