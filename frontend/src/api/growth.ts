import { AI_EXECUTION_TIMEOUT_MS, apiClient } from "./client";
import type {
  CampaignUploadResponse,
  FeedbackContext,
  GrowthAnalysis,
  GrowthOptimizationPolicy,
  GrowthOptimizationExecution,
  GrowthOptimizationExecutionPreflight,
  GrowthOptimizationExecutionResult,
  GrowthOptimizationRun,
  GrowthOptimizationRunActivateResult,
  GrowthOptimizationRunCreateResult,
  GrowthRecommendationPreflight,
} from "../types/growth";
import type {
  V2CopyExecutionRequest,
  V2CopyExecutionResult,
  V2CopyPreflight,
  V2CopySourceRequest,
} from "../types/copy";

export async function uploadCampaignCsv(
  productId: number,
  file: File,
  signal?: AbortSignal,
): Promise<CampaignUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<CampaignUploadResponse>(
    `/products/${productId}/campaigns/upload`,
    formData,
    { signal },
  );
  return response.data;
}

export async function getFeedbackContext(
  productId: number,
  signal?: AbortSignal,
): Promise<FeedbackContext> {
  const response = await apiClient.get<FeedbackContext>(
    `/products/${productId}/feedback-context`,
    { signal },
  );
  return response.data;
}

export async function getGrowthRecommendationPreflight(
  productId: number,
  signal?: AbortSignal,
): Promise<GrowthRecommendationPreflight> {
  const response = await apiClient.get<GrowthRecommendationPreflight>(
    `/products/${productId}/growth-analysis/preflight`,
    { signal },
  );
  return response.data;
}

export async function executeGrowthRecommendation(
  productId: number,
  expectedContextDigest: string,
  signal?: AbortSignal,
): Promise<GrowthAnalysis> {
  const response = await apiClient.post<GrowthAnalysis>(
    `/products/${productId}/growth-analysis`,
    { expected_context_digest: expectedContextDigest },
    { signal, timeout: AI_EXECUTION_TIMEOUT_MS },
  );
  return response.data;
}

export async function createGrowthOptimizationRun(
  productId: number,
  analysis: GrowthAnalysis,
  policy: GrowthOptimizationPolicy,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<GrowthOptimizationRunCreateResult> {
  const response = await apiClient.post<GrowthOptimizationRunCreateResult>(
    `/products/${productId}/growth-optimization/plans`,
    {
      analysis,
      policy,
      idempotency_key: idempotencyKey,
      activate_internal: true,
    },
    { signal },
  );
  return response.data;
}

export async function listGrowthOptimizationRuns(
  productId: number,
  signal?: AbortSignal,
): Promise<GrowthOptimizationRun[]> {
  const response = await apiClient.get<GrowthOptimizationRun[]>(
    `/products/${productId}/growth-optimization/plans`,
    { signal },
  );
  return response.data;
}

export async function activateGrowthOptimizationRun(
  productId: number,
  runId: number,
  signal?: AbortSignal,
): Promise<GrowthOptimizationRunActivateResult> {
  const response = await apiClient.post<GrowthOptimizationRunActivateResult>(
    `/products/${productId}/growth-optimization/plans/${runId}/activate`,
    undefined,
    { signal },
  );
  return response.data;
}

export async function preflightGrowthOptimizationExecution(
  productId: number,
  runId: number,
  signal?: AbortSignal,
): Promise<GrowthOptimizationExecutionPreflight> {
  const response = await apiClient.get<GrowthOptimizationExecutionPreflight>(
    `/products/${productId}/growth-optimization/plans/${runId}/execution-preflight`,
    { signal },
  );
  return response.data;
}

export async function executeGrowthOptimizationSandbox(
  productId: number,
  runId: number,
  idempotencyKey: string,
  expectedContextDigest: string,
  signal?: AbortSignal,
): Promise<GrowthOptimizationExecutionResult> {
  const response = await apiClient.post<GrowthOptimizationExecutionResult>(
    `/products/${productId}/growth-optimization/plans/${runId}/sandbox-executions`,
    {
      idempotency_key: idempotencyKey,
      expected_context_digest: expectedContextDigest,
      confirm_sandbox_execution: true,
    },
    { signal },
  );
  return response.data;
}

export async function listGrowthOptimizationExecutions(
  productId: number,
  signal?: AbortSignal,
): Promise<GrowthOptimizationExecution[]> {
  const response = await apiClient.get<GrowthOptimizationExecution[]>(
    `/products/${productId}/growth-optimization/executions`,
    { signal },
  );
  return response.data;
}

export async function rollbackGrowthOptimizationExecution(
  productId: number,
  executionId: number,
  signal?: AbortSignal,
): Promise<GrowthOptimizationExecutionResult> {
  const response = await apiClient.post<GrowthOptimizationExecutionResult>(
    `/products/${productId}/growth-optimization/executions/${executionId}/rollback`,
    undefined,
    { signal },
  );
  return response.data;
}

export async function preflightV2Copy(
  productId: number,
  data: V2CopySourceRequest,
  signal?: AbortSignal,
): Promise<V2CopyPreflight> {
  const response = await apiClient.post<V2CopyPreflight>(
    `/products/${productId}/v2-copy/preflight`,
    data,
    { signal },
  );
  return response.data;
}

export async function executeV2Copy(
  productId: number,
  data: V2CopyExecutionRequest,
  signal?: AbortSignal,
): Promise<V2CopyExecutionResult> {
  const response = await apiClient.post<V2CopyExecutionResult>(
    `/products/${productId}/v2-copy`,
    data,
    { signal, timeout: AI_EXECUTION_TIMEOUT_MS },
  );
  return response.data;
}
