export type ProviderCredential = {
  provider: "DASHSCOPE";
  configured: boolean;
  key_hint: string | null;
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
  verified_at: string | null;
  message: string;
};
