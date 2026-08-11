export type InstagramOAuthStatus = "connected" | "denied" | "failed";

export interface InstagramOperationIdentity {
  productId: number;
  accountId: number | null;
  operationId: number;
  controller: AbortController;
}

export interface InstagramOperationControllers {
  connect: InstagramOperationIdentity | null;
  disconnect: InstagramOperationIdentity | null;
}

export function isCurrentInstagramOperation(
  expected: InstagramOperationIdentity,
  current: InstagramOperationIdentity | null,
): boolean {
  return (
    current !== null &&
    !expected.controller.signal.aborted &&
    expected.productId === current.productId &&
    expected.accountId === current.accountId &&
    expected.operationId === current.operationId &&
    expected.controller === current.controller
  );
}

export function canReleaseInstagramOperationLock(
  expected: InstagramOperationIdentity,
  current: InstagramOperationIdentity | null,
): boolean {
  return isCurrentInstagramOperation(expected, current);
}

export function canStartInstagramOperation(
  connect: InstagramOperationIdentity | null,
  disconnect: InstagramOperationIdentity | null,
): boolean {
  return connect === null && disconnect === null;
}

export function shouldReleaseInstagramConnectLock(
  expected: InstagramOperationIdentity,
  current: InstagramOperationIdentity | null,
  navigationStarted: boolean,
): boolean {
  return (
    !navigationStarted && canReleaseInstagramOperationLock(expected, current)
  );
}

export function cancelInstagramOperations(
  operations: InstagramOperationControllers,
): void {
  operations.connect?.controller.abort();
  operations.disconnect?.controller.abort();
}

export function safeInstagramAuthorizationUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && parsed.hostname === "www.instagram.com"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

export function readInstagramOAuthStatus(search: string): InstagramOAuthStatus | null {
  const value = new URLSearchParams(search).get("instagram_oauth");
  return value === "connected" || value === "denied" || value === "failed"
    ? value
    : null;
}

export function instagramScopeSummary(scopes: string[]): string {
  const allowed = new Set([
    "instagram_business_basic",
    "instagram_business_content_publish",
  ]);
  const safe = scopes.filter((scope) => allowed.has(scope));
  return safe.length === 2 ? "基础身份 · 内容发布权限" : "授权范围不完整";
}
