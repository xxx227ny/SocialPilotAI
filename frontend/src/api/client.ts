import axios from "axios";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
  timeout: 5000,
});

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) return fallback;
  if (error.response?.status === 422) {
    return "请求未通过后端校验，请检查各字段后重试。";
  }
  if (error.response && error.response.status >= 500) {
    return "商品服务暂时不可用，请稍后重试。";
  }
  return fallback;
}
