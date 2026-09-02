import { apiClient } from "./client";
import type {
  CredentialVerification,
  ProviderCredential,
} from "../types/credentials";

export async function getDashScopeCredential(): Promise<ProviderCredential> {
  return (
    await apiClient.get<ProviderCredential>("/credentials/dashscope")
  ).data;
}

export async function saveDashScopeCredential(
  apiKey: string,
  region: "cn-beijing",
  providerWorkspaceId: string,
): Promise<ProviderCredential> {
  return (
    await apiClient.put<ProviderCredential>("/credentials/dashscope", {
      api_key: apiKey,
      region,
      provider_workspace_id: providerWorkspaceId.trim() || null,
    })
  ).data;
}

export async function deleteDashScopeCredential(): Promise<void> {
  await apiClient.delete("/credentials/dashscope");
}

export async function verifyDashScopeCredential(): Promise<CredentialVerification> {
  return (
    await apiClient.post<CredentialVerification>(
      "/credentials/dashscope/verify",
    )
  ).data;
}
