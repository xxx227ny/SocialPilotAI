import { apiClient } from "./client";
import type { ExecutionJob, ExecutionJobCreateResult } from "../types/execution";
import type {
  PublishArtifactCandidate,
  PublishTask,
  SocialAccount,
  InstagramConnectResult,
  TikTokConnectResult,
  InstagramFinalizePreflight,
  InstagramPublishPreflight,
  InstagramPublishingMetadata,
  YouTubeConnectResult,
  YouTubePreflight,
  YouTubePublishingMetadata,
  TikTokCreatorInfoSnapshot,
  TikTokPublishingMetadata,
  TikTokPublishPreflight,
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

export async function connectInstagram(productId: number, signal?: AbortSignal) {
  const response = await apiClient.post<InstagramConnectResult>(
    "/social-accounts/instagram/connect",
    { product_id: productId },
    { signal },
  );
  return response.data;
}

export async function disconnectInstagramAccount(
  productId: number,
  accountId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<{
    account: SocialAccount;
    local_only: true;
    meta_authorization_revoked: false;
  }>(
    `/social-accounts/instagram/${accountId}/disconnect`,
    { product_id: productId, confirm_disconnect: true },
    { signal },
  );
  return response.data.account;
}

export async function connectTikTok(productId: number, signal?: AbortSignal) {
  const response = await apiClient.post<TikTokConnectResult>(
    "/social-accounts/tiktok/connect",
    { product_id: productId },
    { signal },
  );
  return response.data;
}

export async function disconnectTikTokAccount(
  productId: number,
  accountId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.post<{
    account: SocialAccount;
    local_only: true;
    tiktok_authorization_revoked: false;
  }>(
    `/social-accounts/tiktok/${accountId}/disconnect`,
    { product_id: productId, confirm_disconnect: true },
    { signal },
  );
  return response.data.account;
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

export async function listInstagramPublishArtifacts(productId: number, signal?: AbortSignal) {
  const response = await apiClient.get<PublishArtifactCandidate[]>(
    `/products/${productId}/publishing/instagram/artifacts`, { signal },
  );
  return response.data;
}

export async function preflightInstagramPublish(
  productId: number, data: InstagramPublishingMetadata, signal?: AbortSignal,
) {
  const response = await apiClient.post<InstagramPublishPreflight>(
    `/products/${productId}/publishing/instagram/preflight`, data, { signal },
  );
  return response.data;
}

export async function publishInstagram(
  productId: number,
  data: InstagramPublishingMetadata & {
    input_digest: string; preflight_digest: string; preflight_expires_at: string;
    idempotency_key: string; confirm_upload: true;
  }, signal?: AbortSignal,
) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/products/${productId}/publishing/instagram`, data, { signal },
  );
  return response.data;
}

export async function refreshInstagramPublish(
  productId: number, taskId: number, refreshRequestId: string, signal?: AbortSignal,
) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/publish-tasks/${taskId}/instagram/refresh`,
    { product_id: productId, refresh_request_id: refreshRequestId }, { signal },
  );
  return response.data;
}

export async function preflightInstagramFinalize(
  productId: number, taskId: number, signal?: AbortSignal,
) {
  const response = await apiClient.post<InstagramFinalizePreflight>(
    `/publish-tasks/${taskId}/instagram/finalize-preflight`, null,
    { params: { product_id: productId }, signal },
  );
  return response.data;
}

export async function finalizeInstagramPublish(
  taskId: number,
  data: { product_id: number; finalize_request_id: string; input_digest: string;
    preflight_digest: string; preflight_expires_at: string; confirm_public_publish: true },
  signal?: AbortSignal,
) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/publish-tasks/${taskId}/instagram/finalize`, data, { signal },
  );
  return response.data;
}

export async function listInstagramPublishJobs(
  jobType: string, sourceType: string, sourceId: number, signal?: AbortSignal,
) {
  const response = await apiClient.get<ExecutionJob[]>("/execution-jobs", {
    params: { job_type: jobType, source_type: sourceType, source_id: sourceId }, signal,
  });
  return response.data;
}

export const getInstagramPublishJob = getYouTubePublishJob;

export async function queryTikTokCreatorInfo(productId: number, socialAccountId: number, signal?: AbortSignal) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/products/${productId}/publishing/tiktok/creator-info`,
    { social_account_id: socialAccountId, request_id: crypto.randomUUID() },
    { signal });
  return response.data;
}

export async function getTikTokCreatorInfoSnapshot(
  snapshotId: number, productId: number, socialAccountId: number,
  signal?: AbortSignal,
) {
  const response = await apiClient.get<TikTokCreatorInfoSnapshot>(
    `/tiktok-creator-info-snapshots/${snapshotId}`,
    { params: { product_id: productId, social_account_id: socialAccountId }, signal });
  return response.data;
}

export async function listTikTokPublishArtifacts(productId: number, signal?: AbortSignal) {
  const response = await apiClient.get<PublishArtifactCandidate[]>(
    `/products/${productId}/publishing/tiktok/artifacts`, { signal });
  return response.data;
}

export async function preflightTikTokPublish(productId: number, data: TikTokPublishingMetadata, signal?: AbortSignal) {
  const response = await apiClient.post<TikTokPublishPreflight>(
    `/products/${productId}/publishing/tiktok/preflight`, data, { signal });
  return response.data;
}

export async function publishTikTok(productId: number, data: TikTokPublishingMetadata & {
  input_digest: string; preflight_digest: string; preflight_expires_at: string; confirm_upload: true;
}, signal?: AbortSignal) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/products/${productId}/publishing/tiktok`, data, { signal });
  return response.data;
}

export async function refreshTikTokPublish(productId: number, taskId: number, refreshRequestId: string, signal?: AbortSignal) {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/publish-tasks/${taskId}/tiktok/refresh`,
    { product_id: productId, refresh_request_id: refreshRequestId }, { signal });
  return response.data;
}
