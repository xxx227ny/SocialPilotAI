import axios from "axios";

import type {
  CopyExecutionIssue,
  CopyExecutionResult,
  CopyMatrix,
  CopyPreflight,
  PersistedCopyMatrix,
} from "../types/copy";
import type {
  ExecutionJob,
  ExecutionJobCreateResult,
} from "../types/execution";
import { apiClient } from "./client";

export async function generateCopyMatrix(productId: number): Promise<CopyMatrix> {
  const response = await apiClient.post<CopyMatrix>(`/products/${productId}/copy`);
  return response.data;
}

export async function getCopyPreflight(
  taskId: number,
  strategyId: number,
  signal?: AbortSignal,
): Promise<CopyPreflight> {
  const response = await apiClient.get<CopyPreflight>(
    `/marketing-tasks/${taskId}/strategies/${strategyId}/copy-preflight`,
    { signal },
  );
  return response.data;
}

export async function enqueueCopyJob(
  taskId: number,
  strategyId: number,
  payload: {
    product_id: number;
    strategy_id: number;
    input_digest: string;
    preflight_digest: string;
    preflight_expires_at: string;
    cost_confirmed: true;
  },
  signal?: AbortSignal,
): Promise<ExecutionJobCreateResult> {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/marketing-tasks/${taskId}/strategies/${strategyId}/copy-jobs`,
    payload,
    { signal },
  );
  return response.data;
}

export async function listCopyJobs(
  strategyId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob[]> {
  const response = await apiClient.get<ExecutionJob[]>("/execution-jobs", {
    params: {
      job_type: "qwen.copy_matrix.generate.v1",
      source_type: "marketing_strategy",
      source_id: strategyId,
    },
    signal,
  });
  return response.data;
}

export async function getCopyExecutionJob(
  jobId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob> {
  const response = await apiClient.get<ExecutionJob>(
    `/execution-jobs/${jobId}`,
    { signal },
  );
  return response.data;
}

export async function retryCopyExecutionJob(
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

export async function getExactCopyMatrix(
  taskId: number,
  strategyId: number,
  copyMatrixId: number,
  signal?: AbortSignal,
): Promise<PersistedCopyMatrix> {
  const response = await apiClient.get<PersistedCopyMatrix>(
    `/marketing-tasks/${taskId}/strategies/${strategyId}/copies/${copyMatrixId}`,
    { signal },
  );
  return response.data;
}

export async function generateTaskBoundCopyMatrix(
  taskId: number,
  strategyId: number,
  signal?: AbortSignal,
): Promise<CopyExecutionResult> {
  const response = await apiClient.post<CopyExecutionResult>(
    `/marketing-tasks/${taskId}/strategies/${strategyId}/copy`,
    undefined,
    { signal },
  );
  return response.data;
}

export async function getLatestCopyForStrategy(
  strategyId: number,
  signal?: AbortSignal,
): Promise<PersistedCopyMatrix> {
  const response = await apiClient.get<PersistedCopyMatrix>(
    `/strategies/${strategyId}/copy/latest`,
    { signal },
  );
  return response.data;
}

export function isCopyNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

export function classifyCopyExecutionError(
  error: unknown,
): CopyExecutionIssue {
  const status = axios.isAxiosError(error) ? error.response?.status : undefined;
  const rawMessage = axios.isAxiosError<{
    detail?: string;
    error?: { message?: string };
  }>(error)
    ? error.response?.data?.detail ??
      error.response?.data?.error?.message ??
      error.message
    : error instanceof Error
      ? error.message
      : "";
  const normalized = rawMessage.toLowerCase();

  if (
    status === 503 &&
    normalized.includes("execution") &&
    normalized.includes("disabled")
  ) {
    return {
      category: "execution-disabled",
      message: "服务端尚未授权真实 Copy 执行。",
      retryable: false,
    };
  }
  if (
    status === 401 ||
    status === 403 ||
    normalized.includes("authentication")
  ) {
    return {
      category: "authentication",
      message: "Provider 身份验证或权限检查失败，请检查服务端凭据。",
      retryable: false,
    };
  }
  if (
    status === 429 ||
    normalized.includes("quota") ||
    normalized.includes("rate limit")
  ) {
    return {
      category: "quota",
      message: "Provider Credits、配额或速率限制阻止了本次请求。",
      retryable: true,
    };
  }
  if (
    status === 503 &&
    (normalized.includes("configured") ||
      normalized.includes("configuration"))
  ) {
    return {
      category: "configuration",
      message: "Provider 尚未完成安全配置。",
      retryable: false,
    };
  }
  if (
    status === 409 ||
    normalized.includes("different products") ||
    normalized.includes("association")
  ) {
    return {
      category: "association",
      message: "MarketingBrief、Strategy 与 Product 身份不一致。",
      retryable: false,
    };
  }
  if (
    status === 502 &&
    normalized.includes("invalid") &&
    normalized.includes("copy")
  ) {
    return {
      category: normalized.includes("platform")
        ? "platform-mismatch"
        : "invalid-output",
      message:
        "Provider 返回的 Copy 格式或平台集合无效，未保存本次结果。",
      retryable: true,
    };
  }
  if (
    status === 503 ||
    status === 504 ||
    normalized.includes("connection") ||
    normalized.includes("timeout")
  ) {
    return {
      category: "network",
      message: "Provider 网络请求失败或超时，将先核对该 Strategy 的最新结果。",
      retryable: true,
    };
  }
  if (status === 404) {
    return {
      category: "not-found",
      message: "未找到对应 Brief、Strategy、Product 或 Copy Matrix。",
      retryable: false,
    };
  }
  if (typeof status === "number" && status >= 500) {
    return {
      category: "backend",
      message: "Backend 暂时无法完成 Copy 生成。",
      retryable: true,
    };
  }
  return {
    category: "unknown",
    message: "Copy 生成状态不确定，将先核对该 Strategy 的最新结果。",
    retryable: true,
  };
}
