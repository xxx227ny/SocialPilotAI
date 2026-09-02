export type ProviderCredential = {
  provider: "DASHSCOPE";
  configured: boolean;
  key_hint: string | null;
  region: "cn-beijing";
  provider_workspace_id: string | null;
  verified: boolean;
  verified_at: string | null;
  updated_at: string | null;
};

export type CredentialVerificationStatus =
  | "VERIFIED"
  | "INVALID"
  | "FORBIDDEN"
  | "RATE_LIMITED"
  | "UNAVAILABLE";

export type CredentialVerification = {
  provider: "DASHSCOPE";
  status: CredentialVerificationStatus;
  verified: boolean;
  key_hint: string;
  region: "cn-beijing";
  provider_workspace_id: string | null;
  verified_at: string | null;
  message: string;
};
