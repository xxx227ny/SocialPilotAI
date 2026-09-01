import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from "axios";

export const READ_TIMEOUT_MS = 10_000;
export const MAX_READ_RETRIES = 1;
type ReadConfig = InternalAxiosRequestConfig & { __readRetryCount?: number };
type Signal = InternalAxiosRequestConfig["signal"];

function isRead(config: InternalAxiosRequestConfig) {
  return ["get", "head"].includes((config.method ?? "get").toLowerCase());
}

export function waitForReadRetry(milliseconds: number, signal?: Signal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new axios.CanceledError());
    const done = () => {
      signal?.removeEventListener?.("abort", cancel);
      resolve();
    };
    const timer = setTimeout(done, milliseconds);
    const cancel = () => {
      clearTimeout(timer);
      signal?.removeEventListener?.("abort", cancel);
      reject(new axios.CanceledError());
    };
    signal?.addEventListener?.("abort", cancel, { once: true });
  });
}

// Never replay POST/PUT/PATCH/DELETE, auth requests, or cancelled requests.
// In particular, generation and production advancement can have billable effects.
export function installReadResilience(
  client: AxiosInstance,
  wait = waitForReadRetry,
) {
  client.interceptors.request.use((config) => {
    if (isRead(config) && config.timeout === client.defaults.timeout) {
      config.timeout = READ_TIMEOUT_MS;
    }
    return config;
  });
  client.interceptors.response.use(undefined, async (error: unknown) => {
    if (!axios.isAxiosError(error)) throw error;
    const config = error.config as ReadConfig | undefined;
    if (!config || !isRead(config) || config.signal?.aborted || axios.isCancel(error)) throw error;
    if (/\/auth(?:\/|$)/.test(config.url ?? "")) throw error;
    const status = error.response?.status;
    const transient = status !== undefined
      ? [408, 502, 503, 504, 520, 521, 522, 523, 524].includes(status)
      : ["ERR_NETWORK", "ECONNABORTED", "ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "ENOTFOUND"].includes(error.code ?? "");
    if (!transient || (config.__readRetryCount ?? 0) >= MAX_READ_RETRIES) throw error;
    config.__readRetryCount = (config.__readRetryCount ?? 0) + 1;
    await wait(1000, config.signal);
    return client.request(config);
  });
}
