import axios from "axios";

import type {
  MarketingStrategy,
  MarketingStrategyExecutionResult,
  StrategyExecutionIssue,
  StrategyPreflight,
} from "../types/strategy";
import type {
  ExecutionJob,
  ExecutionJobCreateResult,
} from "../types/execution";
import { apiClient } from "./client";

export async function generateMarketingStrategy(
  taskId: number,
  signal?: AbortSignal,
): Promise<MarketingStrategyExecutionResult> {
  const response = await apiClient.post<MarketingStrategyExecutionResult>(
    `/marketing-tasks/${taskId}/strategy`,
    undefined,
    { signal },
  );
  return response.data;
}

export async function getLatestMarketingStrategy(
  productId: number,
  signal?: AbortSignal,
): Promise<MarketingStrategy> {
  const response = await apiClient.get<MarketingStrategy>(
    `/products/${productId}/strategies/latest`,
    { signal },
  );
  return response.data;
}

export function classifyStrategyExecutionError(
  error: unknown,
): StrategyExecutionIssue {
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
      message: "服务端尚未授权真实执行。",
      retryable: false,
    };
  }
  if (status === 401 || status === 403 || normalized.includes("authentication")) {
    return { category: "authentication", message: "Provider 身份验证失败，请检查服务端凭据配置。", retryable: false };
  }
  if (status === 429 || normalized.includes("quota") || normalized.includes("rate limit")) {
    return { category: "quota", message: "Provider 配额或速率限制阻止了本次请求，请稍后重试或检查账户额度。", retryable: true };
  }
  if (status === 503 && (normalized.includes("configured") || normalized.includes("configuration"))) {
    return { category: "configuration", message: "Provider 尚未完成安全配置，无法执行真实策略生成。", retryable: false };
  }
  if (status === 502 && normalized.includes("invalid")) {
    return { category: "invalid-output", message: "Provider 返回了无法解析的策略结果，未保存无效内容。", retryable: true };
  }
  if (
    status === 503 ||
    status === 504 ||
    normalized.includes("connection") ||
    normalized.includes("timeout")
  ) {
    return { category: "network", message: "Provider 网络请求失败，请检查网络后重试。", retryable: true };
  }
  if (status === 404) {
    return { category: "not-found", message: "未找到对应商品或策略记录，请刷新商品状态后重试。", retryable: false };
  }
  if (typeof status === "number" && status >= 500) {
    return { category: "backend", message: "后端暂时无法完成策略生成，请稍后重试。", retryable: true };
  }
  return { category: "unknown", message: "策略生成未能完成，请重试；若持续失败，请检查服务端日志。", retryable: true };
}

export async function getStrategyPreflight(
  taskId: number,
  signal?: AbortSignal,
): Promise<StrategyPreflight> {
  const response = await apiClient.get<StrategyPreflight>(
    `/marketing-tasks/${taskId}/strategy-preflight`,
    { signal },
  );
  return response.data;
}

export async function enqueueStrategyJob(
  taskId: number,
  payload: {
    product_id: number;
    input_digest: string;
    preflight_digest: string;
    preflight_expires_at: string;
    cost_confirmed: true;
  },
  signal?: AbortSignal,
): Promise<ExecutionJobCreateResult> {
  const response = await apiClient.post<ExecutionJobCreateResult>(
    `/marketing-tasks/${taskId}/strategy-jobs`,
    payload,
    { signal },
  );
  return response.data;
}

export async function listStrategyJobs(
  taskId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob[]> {
  const response = await apiClient.get<ExecutionJob[]>("/execution-jobs", {
    params: {
      job_type: "qwen.strategy.generate.v1",
      source_type: "marketing_brief",
      source_id: taskId,
    },
    signal,
  });
  return response.data;
}

export async function getExecutionJob(
  jobId: number,
  signal?: AbortSignal,
): Promise<ExecutionJob> {
  const response = await apiClient.get<ExecutionJob>(
    `/execution-jobs/${jobId}`,
    { signal },
  );
  return response.data;
}

export async function retryExecutionJob(
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

export async function getExactMarketingStrategy(
  taskId: number,
  strategyId: number,
  signal?: AbortSignal,
): Promise<MarketingStrategy> {
  const response = await apiClient.get<MarketingStrategy>(
    `/marketing-tasks/${taskId}/strategies/${strategyId}`,
    { signal },
  );
  return response.data;
}
