import { AI_EXECUTION_TIMEOUT_MS, apiClient } from "./client";
import type {
  InitialVideoProjectExecutionRequest,
  InitialVideoProjectPreflight,
  InitialVideoProjectSource,
  InitialVideoProjectSourceRequest,
  LiveRenderTaskResponse,
  VideoProject,
  VideoProjectRequest,
  VideoRenderArtifact,
  VideoRenderArtifactSafe,
  VideoRenderOperation,
  VideoRenderPreflight,
  VideoRenderRefreshJobRequest,
  VideoRenderSubmitJobRequest,
  V2VideoProjectExecutionRequest,
  V2VideoProjectExecutionResult,
  V2VideoProjectPreflight,
  V2VideoProjectSourceRequest,
} from "../types/video";
import type {
  ExecutionJob,
  ExecutionJobCreateResult,
} from "../types/execution";
import axios from "axios";

export interface InitialVideoOperationIdentity {
  productId: number;
  operationId: number;
  controller: AbortController;
}

export function isCurrentInitialVideoOperation(
  expected: InitialVideoOperationIdentity,
  currentProductId: number,
  currentOperationId: number,
  currentController: AbortController | null,
): boolean {
  return (
    !expected.controller.signal.aborted &&
    expected.productId === currentProductId &&
    expected.operationId === currentOperationId &&
    expected.controller === currentController
  );
}

export async function generateVideoProject(
  productId: number,
  payload: VideoProjectRequest,
): Promise<VideoProject> {
  const response = await apiClient.post<VideoProject>(
    `/products/${productId}/video-projects`,
    payload,
  );
  return response.data;
}

export async function preflightInitialVideoProject(
  productId: number,
  payload: InitialVideoProjectSourceRequest,
  signal?: AbortSignal,
): Promise<InitialVideoProjectPreflight> {
  const response = await apiClient.post<InitialVideoProjectPreflight>(
    `/products/${productId}/video-projects/preflight`,
    payload,
    { signal },
  );
  return response.data;
}

export async function getInitialVideoProjectSource(
  productId: number,
  signal?: AbortSignal,
): Promise<InitialVideoProjectSource> {
  const response = await apiClient.get<InitialVideoProjectSource>(
    `/products/${productId}/video-projects/source`,
    { signal },
  );
  return response.data;
}

export async function enqueueInitialVideoProject(
  productId: number,
  payload: InitialVideoProjectExecutionRequest,
  signal?: AbortSignal,
): Promise<ExecutionJobCreateResult> {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/products/${productId}/video-projects/execute`,
    payload,
    { signal },
  );
  return response.data;
}

export async function listInitialVideoProjectJobs(
  productId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob[]> {
  const response = await apiClient.get<ExecutionJob[]>("/execution-jobs", {
    params: {
      job_type: "qwen.video_project.generate.v1",
      source_type: "product",
      source_id: productId,
    },
    signal,
  });
  return response.data;
}

export async function getInitialVideoProjectJob(
  jobId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob> {
  const response = await apiClient.get<ExecutionJob>(
    `/execution-jobs/${jobId}`,
    { signal },
  );
  return response.data;
}

export async function retryInitialVideoProjectJob(
  jobId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob> {
  const response = await apiClient.post<ExecutionJob>(
    `/execution-jobs/${jobId}/retry`,
    { retry_confirmed: true },
    { signal },
  );
  return response.data;
}

export async function preflightV2VideoProject(
  productId: number,
  payload: V2VideoProjectSourceRequest,
  signal?: AbortSignal,
): Promise<V2VideoProjectPreflight> {
  const response = await apiClient.post<V2VideoProjectPreflight>(
    `/products/${productId}/v2-video-project/preflight`,
    payload,
    { signal },
  );
  return response.data;
}

export async function executeV2VideoProject(
  productId: number,
  payload: V2VideoProjectExecutionRequest,
  signal?: AbortSignal,
): Promise<V2VideoProjectExecutionResult> {
  const response = await apiClient.post<V2VideoProjectExecutionResult>(
    `/products/${productId}/v2-video-project`,
    payload,
    { signal, timeout: AI_EXECUTION_TIMEOUT_MS },
  );
  return response.data;
}

export async function getLatestVideoProjectForProduct(
  productId: number,
  signal?: AbortSignal,
): Promise<VideoProject> {
  const response = await apiClient.get<VideoProject>(
    `/products/${productId}/video-projects/latest`,
    { signal },
  );
  return response.data;
}

export async function getVideoProject(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoProject> {
  const response = await apiClient.get<VideoProject>(
    `/video-projects/${videoProjectId}`,
    { signal },
  );
  return response.data;
}

export async function getVideoRenderPreflight(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoRenderPreflight> {
  const response = await apiClient.get<VideoRenderPreflight>(
    `/video-projects/${videoProjectId}/render-preflight`,
    { signal },
  );
  return response.data;
}

export function isVideoProjectNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

export function isVideoRenderTaskNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

export async function executeVideoProjectRender(
  videoProjectId: number,
  payload: VideoRenderSubmitJobRequest,
  signal?: AbortSignal,
): Promise<ExecutionJobCreateResult> {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/video-projects/${videoProjectId}/render-execution`,
    payload,
    { signal },
  );
  return response.data;
}

export async function getLatestVideoRenderTask(
  videoProjectId: number,
  signal?: AbortSignal,
): Promise<VideoRenderOperation> {
  const response = await apiClient.get<VideoRenderOperation>(
    `/video-projects/${videoProjectId}/render-tasks/latest`,
    { signal },
  );
  return response.data;
}

export async function recoverVideoRenderTask(
  taskId: number,
  signal?: AbortSignal,
): Promise<VideoRenderOperation> {
  const response = await apiClient.get<VideoRenderOperation>(
    `/video-render-tasks/${taskId}/recovery`,
    { signal },
  );
  return response.data;
}

export async function refreshWorkspaceVideoRenderTask(
  taskId: number,
  payload: VideoRenderRefreshJobRequest,
  signal?: AbortSignal,
): Promise<ExecutionJobCreateResult> {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/video-render-tasks/${taskId}/refresh`,
    payload,
    { signal },
  );
  return response.data;
}

export async function listVideoRenderJobs(
  jobType: "wanx.video_render.submit.v1" | "wanx.video_render.refresh.v1",
  sourceType: "video_project" | "video_render_task",
  sourceId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob[]> {
  const response = await apiClient.get<ExecutionJob[]>("/execution-jobs", {
    params: {
      job_type: jobType,
      source_type: sourceType,
      source_id: sourceId,
    },
    signal,
  });
  return response.data;
}

export async function getVideoRenderJob(
  jobId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob> {
  const response = await apiClient.get<ExecutionJob>(
    `/execution-jobs/${jobId}`,
    { signal },
  );
  return response.data;
}

export async function getVideoRenderArtifactMetadata(
  artifactId: number,
  signal?: AbortSignal,
): Promise<VideoRenderArtifactSafe> {
  const response = await apiClient.get<VideoRenderArtifactSafe>(
    `/video-render-artifacts/${artifactId}`,
    { signal },
  );
  return response.data;
}

export function getVideoRenderArtifactContentUrl(artifactId: number): string {
  const baseUrl = apiClient.defaults.baseURL?.replace(/\/$/, "") ?? "";
  return `${baseUrl}/video-render-artifacts/${artifactId}/content`;
}

export function getVideoRenderArtifactPreviewUrl(artifactId: number): string {
  const baseUrl = apiClient.defaults.baseURL?.replace(/\/$/, "") ?? "";
  return `${baseUrl}/video-render-artifacts/${artifactId}/preview`;
}

export async function downloadVideoRenderArtifact(
  artifactId: number,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await apiClient.get<Blob>(
    `/video-render-artifacts/${artifactId}/download`,
    { responseType: "blob", signal },
  );
  return response.data;
}

export async function getVideoRenderArtifacts(
  videoProjectId: number,
): Promise<VideoRenderArtifact[]> {
  const response = await apiClient.get<VideoRenderArtifact[]>(
    `/video-projects/${videoProjectId}/render-artifacts`,
  );
  return response.data;
}

export async function createLiveVideoRender(
  videoProjectId: number,
): Promise<LiveRenderTaskResponse> {
  const response = await apiClient.post<LiveRenderTaskResponse>(
    `/video-projects/${videoProjectId}/live-render`,
    { confirm_live_generation: true },
  );
  return response.data;
}

export async function refreshVideoRenderTask(
  taskId: number,
): Promise<LiveRenderTaskResponse> {
  const response = await apiClient.post<LiveRenderTaskResponse>(
    `/video-render-tasks/${taskId}/refresh`,
  );
  return response.data;
}
