import { apiClient } from "./client";
import type { ExecutionJob, ExecutionJobCreateResult } from "../types/execution";
import type {
  PublishArtifactCandidate,
  PublishTask,
  SocialAccount,
  YouTubeConnectResult,
  YouTubePreflight,
  YouTubePublishingMetadata,
} from "../types/social";

export async function connectYouTube(
  productId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<YouTubeConnectResult>(
    "/social-accounts/youtube/connect",
    { product_id: productId },
    { signal },
  );
  return response.data;
}

export async function listSocialAccounts(
  productId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<SocialAccount[]>("/social-accounts", {
    params: { product_id: productId },
    signal,
  });
  return response.data;
}

export async function disconnectSocialAccount(
  productId: number,
  accountId: number,
  revokeGoogleAuthorization: boolean,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<{ account: SocialAccount }>(
    `/social-accounts/${accountId}/disconnect`,
    {
      product_id: productId,
      revoke_google_authorization: revokeGoogleAuthorization,
      confirm_disconnect: true,
    },
    { signal },
  );
  return response.data.account;
}

export async function listPublishArtifacts(
  productId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<PublishArtifactCandidate[]>(
    `/products/${productId}/publishing/youtube/artifacts`,
    { signal },
  );
  return response.data;
}

export async function preflightYouTubePublish(
  productId: number,
  data: YouTubePublishingMetadata,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<YouTubePreflight>(
    `/products/${productId}/publishing/youtube/preflight`,
    data,
    { signal },
  );
  return response.data;
}

export async function publishYouTube(
  productId: number,
  data: YouTubePublishingMetadata & {
    preflight_digest: string;
    preflight_expires_at: string;
    input_digest: string;
    idempotency_key: string;
    confirm_upload: true;
  },
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/products/${productId}/publishing/youtube`,
    data,
    { signal },
  );
  return response.data;
}

export async function listPublishTasks(
  productId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<PublishTask[]>(
    `/products/${productId}/publish-tasks`,
    { signal },
  );
  return response.data;
}

export async function refreshPublishTask(
  productId: number,
  taskId: number,
  refreshRequestId: string,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/publish-tasks/${taskId}/refresh`,
    { product_id: productId, refresh_request_id: refreshRequestId },
    { signal },
  );
  return response.data;
}

export async function getPublishTask(
  productId: number,
  taskId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<PublishTask>(
    `/publish-tasks/${taskId}`,
    { params: { product_id: productId }, signal },
  );
  return response.data;
}

export async function listYouTubePublishJobs(
  jobType: string,
  sourceType: string,
  sourceId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<ExecutionJob[]>("/execution-jobs", {
    params: { job_type: jobType, source_type: sourceType, source_id: sourceId },
    signal,
  });
  return response.data;
}

export async function getYouTubePublishJob(
  jobId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<ExecutionJob>(
    `/execution-jobs/${jobId}`,
    { signal },
  );
  return response.data;
}
