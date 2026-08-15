import type {
  BatchPlatform,
  BatchVideoCreateResult,
  BatchVideoJob,
  BatchVideoPreflight,
  BatchVideoRequest,
  BatchVideoVariant,
} from "../../types/batchVideo";

export interface BatchOperation {
  id: number;
  batchId: number | null;
  controller: AbortController;
}

export interface BatchOperationSlot {
  current: BatchOperation | null;
}

export interface BatchWorkflowApi {
  preflight: (
    request: BatchVideoRequest,
    signal: AbortSignal,
  ) => Promise<BatchVideoPreflight>;
  create: (
    request: BatchVideoRequest,
    preflight: BatchVideoPreflight,
    signal: AbortSignal,
  ) => Promise<BatchVideoCreateResult>;
  readBatch: (batchId: number, signal: AbortSignal) => Promise<BatchVideoJob>;
  readVariants: (
    batchId: number,
    signal: AbortSignal,
  ) => Promise<BatchVideoVariant[]>;
  control: (
    batchId: number,
    action: "pause" | "resume" | "cancel",
    signal: AbortSignal,
  ) => Promise<BatchVideoJob>;
}

export interface BatchSnapshot {
  batch: BatchVideoJob;
  variants: BatchVideoVariant[];
}

const TERMINAL_BATCH_STATUSES = new Set([
  "READY_FOR_SCRIPT",
  "FAILED",
  "CANCELLED",
  "PARTIAL_FAILED",
  "MIXED_TERMINAL",
]);

export function expandedVariantCount(
  productIds: number[],
  platforms: BatchPlatform[],
  variantsPerPlatform: number,
) {
  return new Set(productIds).size * new Set(platforms).size * variantsPerPlatform;
}

export function beginBatchOperation(slot: BatchOperationSlot, operation: BatchOperation) {
  if (slot.current !== null) return false;
  slot.current = operation;
  return true;
}

export function isCurrentBatchOperation(
  operation: BatchOperation,
  current: BatchOperation | null,
) {
  return (
    current === operation &&
    current.id === operation.id &&
    current.batchId === operation.batchId &&
    current.controller === operation.controller
  );
}

export function finishBatchOperation(slot: BatchOperationSlot, operation: BatchOperation) {
  if (!isCurrentBatchOperation(operation, slot.current)) return false;
  slot.current = null;
  return true;
}

export function abortBatchOperation(slot: BatchOperationSlot) {
  slot.current?.controller.abort();
  slot.current = null;
}

export async function createBatchWorkflow(
  api: BatchWorkflowApi,
  request: BatchVideoRequest,
  signal: AbortSignal,
) {
  const checked = await api.preflight(request, signal);
  return api.create(request, checked, signal);
}

export async function recoverExactBatchWorkflow(
  api: BatchWorkflowApi,
  batchId: number,
  signal: AbortSignal,
): Promise<BatchSnapshot> {
  const batch = await api.readBatch(batchId, signal);
  const variants = await api.readVariants(batchId, signal);
  return { batch, variants };
}

export async function controlBatchWorkflow(
  api: BatchWorkflowApi,
  batchId: number,
  action: "pause" | "resume" | "cancel",
  signal: AbortSignal,
): Promise<BatchSnapshot> {
  await api.control(batchId, action, signal);
  return recoverExactBatchWorkflow(api, batchId, signal);
}

export async function pollBatchSerial(options: {
  batchId: number;
  signal: AbortSignal;
  read: (batchId: number, signal: AbortSignal) => Promise<BatchSnapshot>;
  delay: (signal: AbortSignal) => Promise<void>;
  update: (snapshot: BatchSnapshot) => void;
  failure: (error: unknown) => void;
}) {
  const { batchId, signal, read, delay, update, failure } = options;
  while (!signal.aborted) {
    await delay(signal);
    if (signal.aborted) return;
    try {
      const snapshot = await read(batchId, signal);
      if (signal.aborted) return;
      update(snapshot);
      if (TERMINAL_BATCH_STATUSES.has(snapshot.batch.status)) return;
    } catch (error) {
      if (!signal.aborted) failure(error);
      return;
    }
  }
}

export function downstreamCostLabel(status: string) {
  return status === "NOT_ESTIMATED" ? "尚未估算" : "成本状态不可用";
}

export function shouldMountBatchVideoFlow(
  featureEnabled: boolean,
  isPresentation: boolean,
) {
  return featureEnabled && !isPresentation;
}

export async function refreshExactBatch(options: {
  operation: BatchOperation;
  current: () => BatchOperation | null;
  read: (batchId: number, signal: AbortSignal) => Promise<BatchVideoVariant[]>;
  update: (variants: BatchVideoVariant[]) => void;
}) {
  const { operation, current, read, update } = options;
  if (operation.batchId === null || !isCurrentBatchOperation(operation, current())) return;
  const variants = await read(operation.batchId, operation.controller.signal);
  if (isCurrentBatchOperation(operation, current())) update(variants);
}
