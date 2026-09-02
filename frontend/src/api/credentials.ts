import { apiClient } from "./client";
import type {
  CredentialVerification,
  ProviderCredential,
} from "../types/credentials";

const BEIJING_WORKSPACE_HOST_SUFFIX = ".cn-beijing.maas.aliyuncs.com";

export function normalizeProviderWorkspaceIdInput(value: string): string {
  const normalized = value.trim().toLowerCase();
  return normalized.endsWith(BEIJING_WORKSPACE_HOST_SUFFIX)
    ? normalized.slice(0, -BEIJING_WORKSPACE_HOST_SUFFIX.length)
    : normalized;
}

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
  const normalizedWorkspaceId = normalizeProviderWorkspaceIdInput(
    providerWorkspaceId,
  );
  return (
    await apiClient.put<ProviderCredential>("/credentials/dashscope", {
      api_key: apiKey,
      region,
      provider_workspace_id: normalizedWorkspaceId || null,
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
