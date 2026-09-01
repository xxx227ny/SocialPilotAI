import { apiClient } from "./client";
import type { ProviderCredential } from "../types/credentials";

export async function getDashScopeCredential(): Promise<ProviderCredential> {
  return (
    await apiClient.get<ProviderCredential>("/credentials/dashscope")
  ).data;
}

export async function saveDashScopeCredential(
  apiKey: string,
): Promise<ProviderCredential> {
  return (
    await apiClient.put<ProviderCredential>("/credentials/dashscope", {
      api_key: apiKey,
    })
  ).data;
}

export async function deleteDashScopeCredential(): Promise<void> {
  await apiClient.delete("/credentials/dashscope");
}
