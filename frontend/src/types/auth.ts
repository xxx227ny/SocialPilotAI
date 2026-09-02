export type AuthSession = {
  enabled: boolean;
  authenticated: boolean;
  username: string | null;
  email?: string | null;
  user_id?: number | null;
  workspace_id?: number | null;
  auth_mode?: "disabled" | "demo" | "user" | null;
  registration_enabled?: boolean | null;
  email_verified?: boolean | null;
};

export type SessionRevocation = {
  revoked_sessions: number;
};

export type AccountAction = {
  message: string;
};
