import axios from "axios";

import type {
  MarketingStrategy,
  StrategyExecutionIssue,
  StrategyPreflight,
} from "../types/strategy";
import { apiClient } from "./client";

export async function generateMarketingStrategy(
  productId: number,
  signal?: AbortSignal,
): Promise<MarketingStrategy> {
  const response = await apiClient.post<MarketingStrategy>(
    `/products/${productId}/strategy`,
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
