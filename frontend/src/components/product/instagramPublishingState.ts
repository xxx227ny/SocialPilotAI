import type { ExecutionJob } from "../../types/execution";

export const INSTAGRAM_PUBLISH_SUBMIT_V1 = "instagram.publish.submit.v1";
export const INSTAGRAM_PUBLISH_REFRESH_V1 = "instagram.publish.refresh.v1";
export const INSTAGRAM_PUBLISH_FINALIZE_V1 = "instagram.publish.finalize.v1";

export interface InstagramPublishIdentity {
  productId: number;
  accountId: number;
  artifactId: number;
  jobId: number | null;
  taskId: number | null;
  operationId: number;
  controller: AbortController;
}

export function isCurrentInstagramPublishOperation(
  expected: InstagramPublishIdentity,
  current: InstagramPublishIdentity | null,
): boolean {
  return current === expected && !expected.controller.signal.aborted;
}

export function canReleaseInstagramPublishLock(
  expected: InstagramPublishIdentity,
  current: InstagramPublishIdentity | null,
): boolean {
  return current === expected;
}

export function cancelInstagramPublishingOperations(
  identities: Array<InstagramPublishIdentity | null>,
): void {
  identities.forEach((identity) => identity?.controller.abort());
}

export function instagramJobNeedsPolling(job: ExecutionJob | null): boolean {
  return job?.status === "QUEUED" || job?.status === "RUNNING";
}

export function shouldAdvanceInstagramPollCycle(
  job: ExecutionJob | null,
  identityIsCurrent: boolean,
): boolean {
  return identityIsCurrent && instagramJobNeedsPolling(job);
}

export function isSameExactInstagramPollJob(
  expected: ExecutionJob,
  received: ExecutionJob,
): boolean {
  return received.id === expected.id
    && received.job_type === expected.job_type
    && received.source_type === expected.source_type
    && received.source_id === expected.source_id;
}

function actionBlockedByJob(job: ExecutionJob | null, jobType: string): boolean {
  return job?.job_type === jobType
    && ["QUEUED", "RUNNING", "SUBMIT_UNKNOWN"].includes(job.status);
}

export function canEnqueueInstagramRefresh(
  taskStatus: string | null,
  job: ExecutionJob | null,
): boolean {
  return taskStatus === "PROCESSING"
    && !actionBlockedByJob(job, INSTAGRAM_PUBLISH_REFRESH_V1);
}

export function canEnqueueInstagramFinalize(
  taskStatus: string | null,
  job: ExecutionJob | null,
): boolean {
  return taskStatus === "READY_TO_PUBLISH"
    && !actionBlockedByJob(job, INSTAGRAM_PUBLISH_FINALIZE_V1);
}

export function isExactInstagramJob(
  job: ExecutionJob,
  jobType: string,
  sourceType: "product" | "publish_task",
  sourceId: number,
): boolean {
  return job.job_type === jobType && job.source_type === sourceType && job.source_id === sourceId;
}

export function exactInstagramPublishTaskId(job: ExecutionJob | null): number | null {
  if (job?.status !== "SUCCEEDED" || job.result_entity_type !== "publish_task") return null;
  const id = job.result_entity_id;
  return Number.isSafeInteger(id) && Number(id) > 0 ? Number(id) : null;
}
