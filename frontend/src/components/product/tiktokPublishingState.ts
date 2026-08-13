import type { ExecutionJob } from "../../types/execution";

export const TIKTOK_CREATOR_INFO_V1 = "tiktok.publish.creator_info.v1";
export const TIKTOK_PUBLISH_SUBMIT_V1 = "tiktok.publish.submit.v1";
export const TIKTOK_PUBLISH_REFRESH_V1 = "tiktok.publish.refresh.v1";

export function isFreshTikTokSnapshot(expiresAt: string, now = Date.now()): boolean {
  const expiry = Date.parse(expiresAt);
  return Number.isFinite(expiry) && expiry > now;
}

export function canSubmitTikTok(job: ExecutionJob | null, confirmed: boolean): boolean {
  return confirmed && (!job || ["FAILED", "CANCELLED"].includes(job.status));
}

export function shouldPollTikTokJob(job: ExecutionJob | null): boolean {
  return Boolean(job && ["QUEUED", "RUNNING"].includes(job.status));
}

export function exactTikTokResultId(job: ExecutionJob | null, type: string): number | null {
  return job?.status === "SUCCEEDED" && job.result_entity_type === type
    && Number.isInteger(job.result_entity_id) && (job.result_entity_id ?? 0) > 0
    ? job.result_entity_id : null;
}

export interface TikTokJobIdentity {
  jobId: number;
  jobType: string;
  sourceType: string;
  sourceId: number;
}

export function isExactTikTokJob(job: ExecutionJob, identity: TikTokJobIdentity): boolean {
  return job.id === identity.jobId && job.job_type === identity.jobType
    && job.source_type === identity.sourceType && job.source_id === identity.sourceId;
}

export function nextTikTokPollAction(
  status: ExecutionJob["status"] | "TRANSIENT_ERROR",
): "continue" | "stop" {
  return ["QUEUED", "RUNNING", "TRANSIENT_ERROR"].includes(status)
    ? "continue" : "stop";
}

export function interactionSettings(
  capabilities: { comment_disabled: boolean; duet_disabled: boolean; stitch_disabled: boolean },
  allowed: { comments: boolean; duet: boolean; stitch: boolean },
) {
  return {
    disable_comment: capabilities.comment_disabled || !allowed.comments,
    disable_duet: capabilities.duet_disabled || !allowed.duet,
    disable_stitch: capabilities.stitch_disabled || !allowed.stitch,
  };
}

export function disclosureValid(organic: boolean, branded: boolean): boolean {
  return organic && (!branded || organic);
}

export interface TikTokOperationIdentity {
  productId: number;
  accountId: number | null;
  snapshotId: number | null;
  artifactId: number | null;
  jobId: number | null;
  taskId: number | null;
  operationId: number;
}

export function isCurrentTikTokOperation(
  expected: TikTokOperationIdentity,
  current: TikTokOperationIdentity,
): boolean {
  return expected.operationId === current.operationId
    && expected.productId === current.productId
    && expected.accountId === current.accountId
    && expected.snapshotId === current.snapshotId
    && expected.artifactId === current.artifactId
    && expected.jobId === current.jobId
    && expected.taskId === current.taskId;
}

export function canReleaseTikTokOperation(
  finishingOperationId: number,
  activeOperationId: number | null,
): boolean {
  return finishingOperationId === activeOperationId;
}

export function canRefreshTikTokTask(
  taskStatus: string | null,
  refreshJobStatus: ExecutionJob["status"] | null,
): boolean {
  return taskStatus === "PROCESSING"
    && refreshJobStatus !== "QUEUED"
    && refreshJobStatus !== "RUNNING";
}

export interface TikTokPollDriver {
  signal: AbortSignal;
  identity: TikTokJobIdentity;
  wait: () => Promise<boolean>;
  read: (signal: AbortSignal) => Promise<ExecutionJob>;
  contextCurrent: () => boolean;
  accept: (job: ExecutionJob) => void;
  transientError: (error: unknown) => void;
}

export async function runTikTokSerialPoll(
  initial: ExecutionJob,
  driver: TikTokPollDriver,
): Promise<ExecutionJob | null> {
  let known = initial;
  while (nextTikTokPollAction(known.status) === "continue") {
    if (driver.signal.aborted || !driver.contextCurrent() || !await driver.wait()) {
      return null;
    }
    if (driver.signal.aborted || !driver.contextCurrent()) return null;
    try {
      const next = await driver.read(driver.signal);
      if (driver.signal.aborted || !driver.contextCurrent()) return null;
      if (!isExactTikTokJob(next, driver.identity)) return null;
      known = next;
      driver.accept(next);
    } catch (error) {
      if (driver.signal.aborted || !driver.contextCurrent()) return null;
      driver.transientError(error);
    }
  }
  return driver.signal.aborted || !driver.contextCurrent() ? null : known;
}
