import { apiClient } from "./client";
import type { AuthSession, SessionRevocation } from "../types/auth";

export async function getAuthSession(): Promise<AuthSession> {
  return (await apiClient.get<AuthSession>("/auth/session")).data;
}

export async function login(
  username: string,
  password: string,
): Promise<AuthSession> {
  return (
    await apiClient.post<AuthSession>("/auth/login", { username, password })
  ).data;
}

export async function register(
  email: string,
  password: string,
  workspaceName?: string,
): Promise<AuthSession> {
  return (
    await apiClient.post<AuthSession>("/auth/register", {
      email,
      password,
      workspace_name: workspaceName?.trim() || null,
    })
  ).data;
}

export async function logout(): Promise<AuthSession> {
  return (await apiClient.post<AuthSession>("/auth/logout")).data;
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<AuthSession> {
  return (
    await apiClient.post<AuthSession>("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    })
  ).data;
}

export async function revokeOtherSessions(): Promise<SessionRevocation> {
  return (
    await apiClient.post<SessionRevocation>("/auth/sessions/revoke-others")
  ).data;
}
