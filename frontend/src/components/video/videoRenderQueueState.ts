import type { ExecutionJob } from "../../types/execution";
import type {
  VideoRenderPreflight,
  VideoRenderSubmitJobRequest,
} from "../../types/video";

export const WANX_VIDEO_RENDER_SUBMIT_V1 = "wanx.video_render.submit.v1";
export const WANX_VIDEO_RENDER_REFRESH_V1 = "wanx.video_render.refresh.v1";

export interface VideoRenderOperationIdentity {
  productId: number;
  videoProjectId: number;
  jobId: number | null;
  renderTaskId: number | null;
  operationId: number;
  controller: AbortController;
}

export interface VideoRenderRequestControllers {
  load: AbortController | null;
  submit: VideoRenderOperationIdentity | null;
  refresh: VideoRenderOperationIdentity | null;
  poll: VideoRenderOperationIdentity | null;
  resultRead: VideoRenderOperationIdentity | null;
}

export function cancelVideoRenderRequestControllers(
  controllers: VideoRenderRequestControllers,
): void {
  controllers.load?.abort();
  controllers.submit?.controller.abort();
  controllers.refresh?.controller.abort();
  controllers.poll?.controller.abort();
  controllers.resultRead?.controller.abort();
}

export function isCurrentVideoRenderOperation(
  expected: VideoRenderOperationIdentity,
  current: VideoRenderOperationIdentity | null,
): boolean {
  return (
    current !== null &&
    !expected.controller.signal.aborted &&
    expected.productId === current.productId &&
    expected.videoProjectId === current.videoProjectId &&
    expected.jobId === current.jobId &&
    expected.renderTaskId === current.renderTaskId &&
    expected.operationId === current.operationId &&
    expected.controller === current.controller
  );
}

export function buildVideoRenderSubmitRequest(
  preflight: VideoRenderPreflight,
): VideoRenderSubmitJobRequest {
  return {
    product_id: preflight.product_id,
    marketing_strategy_id: preflight.marketing_strategy_id,
    copy_matrix_id: preflight.copy_matrix_id,
    input_digest: preflight.input_digest,
    preflight_digest: preflight.preflight_digest,
    preflight_expires_at: preflight.expires_at,
    cost_confirmed: true,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function selectExactVideoRenderSubmitJob(
  jobs: ExecutionJob[],
  videoProjectId: number,
  inputDigest: string,
): ExecutionJob | null {
  return (
    jobs.find((job) => {
      const payload = job.input_payload;
      return (
        job.job_type === WANX_VIDEO_RENDER_SUBMIT_V1 &&
        job.source_type === "video_project" &&
        job.source_id === videoProjectId &&
        job.input_digest === inputDigest &&
        isRecord(payload) &&
        payload.video_project_id === videoProjectId
      );
    }) ?? null
  );
}

export function videoRenderJobNeedsPolling(job: ExecutionJob | null): boolean {
  return job?.status === "QUEUED" || job?.status === "RUNNING";
}

export type VideoRenderPollOutcome = ExecutionJob | "LOCAL_READ_ERROR";

export function shouldContinueVideoRenderPolling(
  expected: VideoRenderOperationIdentity,
  current: VideoRenderOperationIdentity | null,
  outcome: VideoRenderPollOutcome,
): boolean {
  if (!isCurrentVideoRenderOperation(expected, current)) return false;
  if (outcome === "LOCAL_READ_ERROR") return expected.jobId !== null;
  return outcome.id === expected.jobId && videoRenderJobNeedsPolling(outcome);
}

export function exactVideoRenderResult(
  job: ExecutionJob,
): { type: "video_render_task" | "video_render_artifact"; id: number } | null {
  if (
    job.status !== "SUCCEEDED" ||
    !Number.isInteger(job.result_entity_id) ||
    (job.result_entity_id ?? 0) <= 0
  ) {
    return null;
  }
  if (
    job.result_entity_type !== "video_render_task" &&
    job.result_entity_type !== "video_render_artifact"
  ) {
    return null;
  }
  return { type: job.result_entity_type, id: job.result_entity_id as number };
}

export function canStartVideoRenderResultRead(
  currentLock: VideoRenderOperationIdentity | null,
): boolean {
  return currentLock === null;
}

export function canReleaseVideoRenderOperationLock(
  expected: VideoRenderOperationIdentity,
  currentLock: VideoRenderOperationIdentity | null,
): boolean {
  return isCurrentVideoRenderOperation(expected, currentLock);
}
