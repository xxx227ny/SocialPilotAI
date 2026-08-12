export type TikTokOAuthStatus = "connected" | "denied" | "failed";

export interface TikTokOperationIdentity {
  productId: number;
  accountId: number | null;
  operationId: number;
  controller: AbortController;
}

export interface TikTokOperationControllers {
  connect: TikTokOperationIdentity | null;
  disconnect: TikTokOperationIdentity | null;
}

export function isCurrentTikTokOperation(
  expected: TikTokOperationIdentity,
  current: TikTokOperationIdentity | null,
): boolean {
  return current !== null &&
    !expected.controller.signal.aborted &&
    expected.productId === current.productId &&
    expected.accountId === current.accountId &&
    expected.operationId === current.operationId &&
    expected.controller === current.controller;
}

export function canReleaseTikTokOperationLock(
  expected: TikTokOperationIdentity,
  current: TikTokOperationIdentity | null,
): boolean {
  return isCurrentTikTokOperation(expected, current);
}

export function canStartTikTokOperation(
  connect: TikTokOperationIdentity | null,
  disconnect: TikTokOperationIdentity | null,
): boolean {
  return connect === null && disconnect === null;
}

export function shouldReleaseTikTokConnectLock(
  expected: TikTokOperationIdentity,
  current: TikTokOperationIdentity | null,
  navigationStarted: boolean,
): boolean {
  return !navigationStarted && canReleaseTikTokOperationLock(expected, current);
}

export function cancelTikTokOperations(
  operations: TikTokOperationControllers,
): void {
  operations.connect?.controller.abort();
  operations.disconnect?.controller.abort();
}

export function safeTikTokAuthorizationUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" &&
      parsed.hostname === "www.tiktok.com" &&
      parsed.pathname === "/v2/auth/authorize/" &&
      parsed.username === "" && parsed.password === "" && parsed.hash === ""
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

export function readTikTokOAuthStatus(search: string): TikTokOAuthStatus | null {
  const value = new URLSearchParams(search).get("tiktok_oauth");
  return value === "connected" || value === "denied" || value === "failed"
    ? value
    : null;
}

export function tiktokScopeSummary(scopes: string[]): string {
  const allowed = new Set(["user.info.basic", "video.publish"]);
  const safe = scopes.filter((scope) => allowed.has(scope));
  return safe.length === 2 ? "基础身份 · 视频发布权限" : "授权范围不完整";
}
