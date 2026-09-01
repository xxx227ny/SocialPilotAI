import type { CopyPreflight, PersistedCopyMatrix } from "../../types/copy";
import type { ExecutionJob } from "../../types/execution";
import type { MarketingTask } from "../../types/marketing";
import type { MarketingStrategy, StrategyPreflight } from "../../types/strategy";

export type CopyWorkspaceLoadState = "ready" | "blocked";

export interface TimedCacheEntry<T> {
  value: T;
  loadedAt: number;
}

export interface StrategyWorkspaceSnapshot {
  loadState: CopyWorkspaceLoadState;
  preflight: StrategyPreflight;
  job: ExecutionJob | null;
  strategy: MarketingStrategy | null;
  reused: boolean;
}

export interface CopyWorkspaceSnapshot {
  loadState: CopyWorkspaceLoadState;
  preflight: CopyPreflight;
  job: ExecutionJob | null;
  matrix: PersistedCopyMatrix | null;
  reused: boolean;
}

const FRESH_FOR_MS = 30_000;
const latestTasks = new Map<number, TimedCacheEntry<MarketingTask | null>>();
const strategySnapshots = new Map<string, TimedCacheEntry<StrategyWorkspaceSnapshot>>();
const copySnapshots = new Map<string, TimedCacheEntry<CopyWorkspaceSnapshot>>();

function strategyKey(taskId: number, productId: number) {
  return `${taskId}:${productId}`;
}

function copyKey(taskId: number, productId: number, strategyId: number) {
  return `${taskId}:${productId}:${strategyId}`;
}

export function cacheEntryIsFresh(entry: TimedCacheEntry<unknown> | undefined) {
  return Boolean(entry && Date.now() - entry.loadedAt < FRESH_FOR_MS);
}

export function getLatestTaskSnapshot(productId: number) {
  return latestTasks.get(productId);
}

export function setLatestTaskSnapshot(productId: number, value: MarketingTask | null) {
  latestTasks.set(productId, { value, loadedAt: Date.now() });
}

export function getStrategyWorkspaceSnapshot(taskId: number, productId: number) {
  return strategySnapshots.get(strategyKey(taskId, productId));
}

export function setStrategyWorkspaceSnapshot(
  taskId: number,
  productId: number,
  value: StrategyWorkspaceSnapshot,
) {
  strategySnapshots.set(strategyKey(taskId, productId), {
    value,
    loadedAt: Date.now(),
  });
}

export function getCopyWorkspaceSnapshot(
  taskId: number,
  productId: number,
  strategyId: number,
) {
  return copySnapshots.get(copyKey(taskId, productId, strategyId));
}

export function setCopyWorkspaceSnapshot(
  taskId: number,
  productId: number,
  strategyId: number,
  value: CopyWorkspaceSnapshot,
) {
  copySnapshots.set(copyKey(taskId, productId, strategyId), {
    value,
    loadedAt: Date.now(),
  });
}

export function clearCopyWorkspaceCache() {
  latestTasks.clear();
  strategySnapshots.clear();
  copySnapshots.clear();
}
