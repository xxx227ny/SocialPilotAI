import axios from "axios";

import type {
  ProviderFailureDetails,
  ProviderFailurePhase,
  ProviderSafeErrorCode,
} from "../types/growth";

export const AI_EXECUTION_TIMEOUT_MS = 180_000;

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1",
  timeout: 5000,
  withCredentials: true,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401 &&
      !String(error.config?.url ?? "").includes("/auth/login")
    ) {
      window.dispatchEvent(new Event("socialpilot:unauthorized"));
    }
    return Promise.reject(error);
  },
);

export function apiContentUrl(path: string): string {
  const baseUrl = apiClient.defaults.baseURL?.replace(/\/$/, "") ?? "";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

const SAFE_PROVIDER_MESSAGES: Record<string, string> = {
  "Qwen provider authentication failed":
    "Qwen认证失败；请在本机核验QWEN_API_KEY与对应区域和Workspace。",
  "Qwen provider permission denied":
    "Qwen账号、Workspace或模型权限不足；本次请求未保存结果。",
  "Qwen endpoint or model was not found":
    "Qwen Endpoint或模型配置不匹配；本次请求未保存结果。",
  "Qwen request or model parameters are invalid":
    "Qwen请求参数或模型配置无效；本次请求未保存结果。",
  "Qwen provider connection failed":
    "连接Qwen前即失败，本次请求不会自动重试。",
  "Qwen provider is temporarily unavailable":
    "Qwen暂时不可用，请稍后重新Preflight并再次确认费用。",
  "Qwen request result is uncertain":
    "Qwen请求结果不确定；不会自动重试，旧费用授权已失效。",
  "Qwen authentication failed":
    "Qwen身份验证或Workspace权限检查失败；本次请求未保存结果。",
  "Qwen quota or rate limit prevents execution":
    "Qwen配额、Credits或速率限制阻止了本次请求。",
  "Qwen generation failed":
    "Qwen返回了确定性失败；本次请求未保存结果。",
  "Qwen returned invalid recommendation data":
    "Qwen Recommendation响应未通过严格Schema校验；本次结果未保存。",
  "Qwen returned invalid V2 Copy data":
    "Qwen V2 Copy响应未通过严格Schema校验；本次结果未保存。",
  "Qwen returned invalid V2 VideoProject data":
    "Qwen V2 VideoProject响应未通过严格Schema校验；本次结果未保存。",
};

const PROVIDER_FAILURE_PHASES = new Set<ProviderFailurePhase>([
  "connect",
  "request",
  "response",
  "schema",
  "delivery",
]);

const PROVIDER_SAFE_ERROR_CODES = new Set<ProviderSafeErrorCode>([
  "connection_failed",
  "dns_resolution_failed",
  "tcp_connection_refused",
  "connect_timeout",
  "network_unreachable",
  "tls_handshake_failed",
  "tls_certificate_failed",
  "connection_reset_before_request",
  "connection_failed_unknown",
  "proxy_unavailable",
  "invalid_request",
  "authentication_failed",
  "permission_denied",
  "endpoint_or_model_not_found",
  "response_uncertain",
  "rate_or_quota_limited",
  "provider_service_error",
  "invalid_provider_output",
  "delivery_uncertain",
  "provider_error",
]);

const PROVIDER_FAILURE_MESSAGES: Record<ProviderSafeErrorCode, string> = {
  connection_failed: "无法连接Provider；请求未到达Provider，不会自动重试。",
  dns_resolution_failed: "无法解析Provider域名；请求未到达Provider。",
  tcp_connection_refused: "Provider TCP连接被拒绝；请求未到达Provider。",
  connect_timeout: "连接Provider超时；请求未到达Provider。",
  network_unreachable: "当前网络无法到达Provider；请求未到达Provider。",
  tls_handshake_failed: "Provider TLS握手失败；请求未到达模型服务。",
  tls_certificate_failed: "Provider TLS证书验证失败；请求未到达模型服务。",
  connection_reset_before_request: "连接在请求发送前被重置；不会自动重试。",
  connection_failed_unknown: "Provider连接失败；请求未到达Provider。",
  proxy_unavailable: "本地网络代理不可用；请求未到达Provider。",
  invalid_request: "Provider拒绝了请求参数或模型配置。",
  authentication_failed: "Provider认证失败；请在本机核验对应凭据。",
  permission_denied: "Provider账号、Workspace或模型权限不足。",
  endpoint_or_model_not_found: "Provider Endpoint或模型不存在。",
  response_uncertain: "Provider请求结果不确定；不会自动重试。",
  rate_or_quota_limited: "Provider配额或速率限制阻止了请求。",
  provider_service_error: "Provider服务暂时不可用；不会自动重试。",
  invalid_provider_output: "Provider输出未通过严格契约校验。",
  delivery_uncertain: "浏览器未收到Backend结果；请求结果不确定。",
  provider_error: "Provider请求失败；不会自动重试。",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function getProviderFailureDetails(
  error: unknown,
  deliveryFallback = false,
): ProviderFailureDetails | null {
  if (!axios.isAxiosError(error)) return null;
  const data = error.response?.data;
  const candidate =
    isRecord(data) && isRecord(data.error) ? data.error : null;
  if (candidate) {
    const provider = candidate.provider;
    const phase = candidate.phase;
    const providerHttpStatus = candidate.provider_http_status;
    const safeErrorCode = candidate.safe_error_code;
    const requestIdDigest = candidate.request_id_digest;
    const occurredAt = candidate.occurred_at;
    if (
      (provider === "qwen" || provider === "wanx") &&
      typeof phase === "string" &&
      PROVIDER_FAILURE_PHASES.has(phase as ProviderFailurePhase) &&
      (providerHttpStatus === null ||
        (Number.isInteger(providerHttpStatus) &&
          Number(providerHttpStatus) >= 100 &&
          Number(providerHttpStatus) <= 599)) &&
      typeof safeErrorCode === "string" &&
      PROVIDER_SAFE_ERROR_CODES.has(safeErrorCode as ProviderSafeErrorCode) &&
      (requestIdDigest === null ||
        (typeof requestIdDigest === "string" &&
          /^[a-f0-9]{16}$/.test(requestIdDigest))) &&
      typeof candidate.uncertain === "boolean" &&
      typeof candidate.potentially_billable === "boolean" &&
      typeof occurredAt === "string" &&
      !Number.isNaN(Date.parse(occurredAt))
    ) {
      return {
        provider,
        phase: phase as ProviderFailurePhase,
        provider_http_status:
          providerHttpStatus === null ? null : Number(providerHttpStatus),
        safe_error_code: safeErrorCode as ProviderSafeErrorCode,
        request_id_digest: requestIdDigest as string | null,
        uncertain: candidate.uncertain,
        potentially_billable: candidate.potentially_billable,
        occurred_at: occurredAt,
      };
    }
  }
  if (deliveryFallback && !error.response) {
    return {
      provider: "qwen",
      phase: "delivery",
      provider_http_status: null,
      safe_error_code: "delivery_uncertain",
      request_id_digest: null,
      uncertain: true,
      potentially_billable: true,
      occurred_at: new Date().toISOString(),
    };
  }
  return null;
}

export function getProviderFailureMessage(
  failure: ProviderFailureDetails,
): string {
  return PROVIDER_FAILURE_MESSAGES[failure.safe_error_code];
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) return fallback;
  const providerFailure = getProviderFailureDetails(error);
  if (providerFailure) return getProviderFailureMessage(providerFailure);
  if (error.response?.status === 422) {
    return "请求未通过后端校验，请检查各字段后重试。";
  }
  const data = error.response?.data as
    | { error?: { message?: unknown } }
    | undefined;
  const safeProviderMessage =
    typeof data?.error?.message === "string"
      ? SAFE_PROVIDER_MESSAGES[data.error.message]
      : undefined;
  if (safeProviderMessage) return safeProviderMessage;
  if (error.response && error.response.status >= 500) {
    return "商品服务暂时不可用，请稍后重试。";
  }
  return fallback;
}
