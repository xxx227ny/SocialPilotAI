export interface UploadGuard {
  preflightReady: boolean;
  confirmed: boolean;
  uploadLocked: boolean;
  madeForKidsSelected: boolean;
  identityComplete: boolean;
}

export function canSubmitPrivateUpload(guard: UploadGuard): boolean {
  return (
    guard.preflightReady &&
    guard.confirmed &&
    !guard.uploadLocked &&
    guard.madeForKidsSelected &&
    guard.identityComplete
  );
}

export function shouldLoadSocialData(
  isPresentation: boolean,
  accountBindingEnabled: boolean,
  publishingEnabled: boolean,
): boolean {
  return (
    !isPresentation && (accountBindingEnabled || publishingEnabled)
  );
}

export function shouldLoadPublishTaskHistory(
  isPresentation: boolean,
): boolean {
  return !isPresentation;
}

export function invalidatedAuthorization() {
  return {
    preflightDigest: null,
    confirmed: false,
    result: null,
  } as const;
}
interface YouTubeExecutionJob {
  id: number;
  job_type: string;
  source_type: string;
  source_id: number;
  input_digest: string;
  input_payload: unknown;
  status: string;
  result_entity_type: string | null;
  result_entity_id: number | null;
  safe_error_code?: string | null;
}

export const YOUTUBE_PUBLISH_SUBMIT_V1 = "youtube.publish.submit.v1";
export const YOUTUBE_PUBLISH_REFRESH_V1 = "youtube.publish.refresh.v1";

export interface YouTubePublishOperationIdentity {
  productId: number;
  accountId: number | null;
  artifactId: number | null;
  inputDigest: string | null;
  jobId: number | null;
  publishTaskId: number | null;
  operationId: number;
  controller: AbortController;
}

export interface YouTubePublishControllers {
  load: AbortController | null;
  preflight: YouTubePublishOperationIdentity | null;
  submit: YouTubePublishOperationIdentity | null;
  refresh: YouTubePublishOperationIdentity | null;
  poll: YouTubePublishOperationIdentity | null;
  resultRead: YouTubePublishOperationIdentity | null;
}

export function cancelYouTubePublishControllers(
  controllers: YouTubePublishControllers,
): void {
  controllers.load?.abort();
  controllers.preflight?.controller.abort();
  controllers.submit?.controller.abort();
  controllers.refresh?.controller.abort();
  controllers.poll?.controller.abort();
  controllers.resultRead?.controller.abort();
}

export function isCurrentYouTubePublishOperation(
  expected: YouTubePublishOperationIdentity,
  current: YouTubePublishOperationIdentity | null,
): boolean {
  return (
    current !== null &&
    !expected.controller.signal.aborted &&
    expected.productId === current.productId &&
    expected.accountId === current.accountId &&
    expected.artifactId === current.artifactId &&
    expected.inputDigest === current.inputDigest &&
    expected.jobId === current.jobId &&
    expected.publishTaskId === current.publishTaskId &&
    expected.operationId === current.operationId &&
    expected.controller === current.controller
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function selectExactYouTubeSubmitJob<T extends YouTubeExecutionJob>(
  jobs: T[],
  productId: number,
  accountId: number,
  artifactId: number,
  inputDigest: string,
): T | null {
  return (
    jobs.find((job) => {
      const payload = job.input_payload;
      return (
        job.job_type === YOUTUBE_PUBLISH_SUBMIT_V1 &&
        job.source_type === "product" &&
        job.source_id === productId &&
        job.input_digest === inputDigest &&
        isRecord(payload) &&
        payload.product_id === productId &&
        payload.social_account_id === accountId &&
        payload.artifact_id === artifactId &&
        payload.frozen_input_digest === inputDigest &&
        Number.isInteger(payload.publish_task_id) &&
        Number(payload.publish_task_id) > 0
      );
    }) ?? null
  );
}

export function isExactYouTubeRefreshJob(
  job: YouTubeExecutionJob,
  productId: number,
  accountId: number,
  publishTaskId: number,
): boolean {
  const payload = job.input_payload;
  return (
    job.job_type === YOUTUBE_PUBLISH_REFRESH_V1 &&
    job.source_type === "publish_task" &&
    job.source_id === publishTaskId &&
    isRecord(payload) &&
    job.input_digest === payload.frozen_task_digest &&
    payload.product_id === productId &&
    payload.social_account_id === accountId &&
    payload.publish_task_id === publishTaskId
  );
}

export function youtubePublishJobNeedsPolling(
  job: YouTubeExecutionJob | null,
): boolean {
  return job?.status === "QUEUED" || job?.status === "RUNNING";
}

export function youtubePublishFailureMessage(code: string | null | undefined): string {
  return {
    YOUTUBE_METADATA_INVALID_TAGS: "YouTube 拒绝了视频标签；系统已阻止上传，请重新读取自动文案后再试。",
    YOUTUBE_METADATA_INVALID_TITLE: "YouTube 拒绝了视频标题，请修改标题后再试。",
    YOUTUBE_METADATA_INVALID_DESCRIPTION: "YouTube 拒绝了视频描述，请修改描述后再试。",
    YOUTUBE_METADATA_INVALID: "YouTube 拒绝了视频元数据，请重新读取自动文案后再试。",
    YOUTUBE_UPLOAD_LIMIT_EXCEEDED: "该 YouTube 频道已达到上传次数限制，请稍后再试。",
    YOUTUBE_QUOTA_EXCEEDED: "YouTube API 配额暂时不足，请稍后再试。",
    YOUTUBE_PERMISSION_DENIED: "当前 YouTube 授权没有上传权限，请重新连接频道。",
    YOUTUBE_PRIVACY_FORBIDDEN: "当前频道不允许使用所选隐私设置。",
    YOUTUBE_AUTHORIZATION_FAILED: "YouTube 授权已失效，请重新连接频道。",
  }[code ?? ""] ?? "YouTube 未接受本次上传；视频尚未发送，请重新读取后再试。";
}

export type YouTubePublishPollOutcome = YouTubeExecutionJob | "LOCAL_READ_ERROR";

export function shouldContinueYouTubePublishPolling(
  expected: YouTubePublishOperationIdentity,
  current: YouTubePublishOperationIdentity | null,
  outcome: YouTubePublishPollOutcome,
): boolean {
  if (!isCurrentYouTubePublishOperation(expected, current)) return false;
  if (outcome === "LOCAL_READ_ERROR") return expected.jobId !== null;
  return outcome.id === expected.jobId && youtubePublishJobNeedsPolling(outcome);
}

export function exactPublishTaskResult(job: YouTubeExecutionJob): number | null {
  if (
    job.status !== "SUCCEEDED" ||
    job.result_entity_type !== "publish_task" ||
    !Number.isInteger(job.result_entity_id) ||
    (job.result_entity_id ?? 0) <= 0
  ) {
    return null;
  }
  return job.result_entity_id;
}

export function canStartExactYouTubePublishResultRead(
  job: YouTubeExecutionJob | null,
  currentRead: YouTubePublishOperationIdentity | null,
): boolean {
  return (
    currentRead === null &&
    job !== null &&
    exactPublishTaskResult(job) !== null
  );
}

export function isCurrentExactYouTubePublishResultRead(
  expected: YouTubePublishOperationIdentity,
  current: YouTubePublishOperationIdentity | null,
  job: YouTubeExecutionJob | null,
): boolean {
  return (
    job !== null &&
    isCurrentYouTubePublishOperation(expected, current) &&
    job.id === expected.jobId &&
    exactPublishTaskResult(job) === expected.publishTaskId
  );
}

export function canReleaseYouTubePublishLock(
  expected: YouTubePublishOperationIdentity,
  current: YouTubePublishOperationIdentity | null,
): boolean {
  return isCurrentYouTubePublishOperation(expected, current);
}
