export type PinterestOAuthStatus = "connected" | "denied" | "failed";

export interface PinterestOperationIdentity {
  productId: number;
  accountId: number | null;
  operationId: number;
  controller: AbortController;
}

export interface PinterestOperationStore {
  connect: PinterestOperationIdentity | null;
  disconnect: PinterestOperationIdentity | null;
}

export interface PinterestConnectCoordinatorInput {
  store: PinterestOperationStore;
  identity: PinterestOperationIdentity;
  request: (signal: AbortSignal) => Promise<{ authorization_url: string }>;
  navigate: (url: string) => void;
  onError: (error: unknown) => void;
}

export interface PinterestDisconnectCoordinatorInput {
  store: PinterestOperationStore;
  identity: PinterestOperationIdentity;
  request: (signal: AbortSignal) => Promise<unknown>;
  onSuccess: (value: unknown) => void;
  onError: (error: unknown) => void;
}

export function isCurrentPinterestOperation(expected: PinterestOperationIdentity, current: PinterestOperationIdentity | null): boolean {
  return current !== null && !expected.controller.signal.aborted &&
    expected.productId === current.productId && expected.accountId === current.accountId &&
    expected.operationId === current.operationId && expected.controller === current.controller;
}
export function canStartPinterestOperation(connect: PinterestOperationIdentity | null, disconnect: PinterestOperationIdentity | null): boolean { return connect === null && disconnect === null; }
export function canReleasePinterestOperationLock(expected: PinterestOperationIdentity, current: PinterestOperationIdentity | null): boolean { return isCurrentPinterestOperation(expected, current); }
export function shouldReleasePinterestConnectLock(expected: PinterestOperationIdentity, current: PinterestOperationIdentity | null, navigationStarted: boolean): boolean { return !navigationStarted && canReleasePinterestOperationLock(expected, current); }
export function cancelPinterestOperations(operations: {connect: PinterestOperationIdentity | null; disconnect: PinterestOperationIdentity | null}): void { operations.connect?.controller.abort(); operations.disconnect?.controller.abort(); }

export async function coordinatePinterestConnect(
  input: PinterestConnectCoordinatorInput,
): Promise<boolean> {
  if (!canStartPinterestOperation(input.store.connect, input.store.disconnect)) {
    return false;
  }
  input.store.connect = input.identity;
  let navigationStarted = false;
  try {
    const result = await input.request(input.identity.controller.signal);
    if (!isCurrentPinterestOperation(input.identity, input.store.connect)) return true;
    const safeUrl = safePinterestAuthorizationUrl(result.authorization_url);
    if (!safeUrl) throw new Error("Unsafe Pinterest authorization URL");
    input.navigate(safeUrl);
    navigationStarted = true;
  } catch (error) {
    if (isCurrentPinterestOperation(input.identity, input.store.connect)) {
      input.onError(error);
    }
  } finally {
    if (shouldReleasePinterestConnectLock(
      input.identity, input.store.connect, navigationStarted,
    )) input.store.connect = null;
  }
  return true;
}

export async function coordinatePinterestDisconnect(
  input: PinterestDisconnectCoordinatorInput,
): Promise<boolean> {
  if (!canStartPinterestOperation(input.store.connect, input.store.disconnect)) {
    return false;
  }
  input.store.disconnect = input.identity;
  try {
    const result = await input.request(input.identity.controller.signal);
    if (isCurrentPinterestOperation(input.identity, input.store.disconnect)) {
      input.onSuccess(result);
    }
  } catch (error) {
    if (isCurrentPinterestOperation(input.identity, input.store.disconnect)) {
      input.onError(error);
    }
  } finally {
    if (canReleasePinterestOperationLock(
      input.identity, input.store.disconnect,
    )) input.store.disconnect = null;
  }
  return true;
}
export function safePinterestAuthorizationUrl(value: string): string | null {
  try { const parsed = new URL(value); return parsed.protocol === "https:" && parsed.hostname === "www.pinterest.com" && parsed.pathname === "/oauth/" && parsed.username === "" && parsed.password === "" && parsed.hash === "" ? parsed.toString() : null; } catch { return null; }
}
export function readPinterestOAuthStatus(search: string): PinterestOAuthStatus | null { const value = new URLSearchParams(search).get("pinterest_oauth"); return value === "connected" || value === "denied" || value === "failed" ? value : null; }
export function pinterestScopeSummary(scopes: string[]): string {
  const required = new Set([
    "boards:read", "pins:read", "pins:write", "user_accounts:read",
  ]);
  return scopes.length === 4 && scopes.every((scope) => required.has(scope))
    ? "读取账号身份 · 读取 Boards · 读取和创建 Pins"
    : "授权范围不完整";
}
