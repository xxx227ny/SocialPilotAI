import type { ExecutionJob } from "../../types/execution";

export interface EnhancementIdentity {
  productId: number;
  compositionId: number;
  artifactId: number;
  jobId: number;
  operationId: number;
  controller: AbortController;
}

export interface EnhancementOperation {
  controller: AbortController;
  id: number;
}

export interface EnhancementOperationSlot {
  current: EnhancementOperation | null;
}

export function beginEnhancementOperation(
  slot: EnhancementOperationSlot,
  operation: EnhancementOperation,
): boolean {
  if (slot.current !== null) return false;
  slot.current = operation;
  return true;
}

export function finishEnhancementOperation(
  slot: EnhancementOperationSlot,
  operation: EnhancementOperation,
): boolean {
  if (slot.current !== operation) return false;
  slot.current = null;
  return true;
}

export function abortEnhancementOperation(slot: EnhancementOperationSlot): void {
  slot.current?.controller.abort();
  slot.current = null;
}

export function isCurrentEnhancementOperation(expected: EnhancementIdentity, current: EnhancementIdentity | null): boolean {
  return current !== null && !expected.controller.signal.aborted && expected.productId === current.productId && expected.compositionId === current.compositionId && expected.artifactId === current.artifactId && expected.jobId === current.jobId && expected.operationId === current.operationId && expected.controller === current.controller;
}

export function exactEnhancementResult(job: ExecutionJob): number | null {
  return job.status === "SUCCEEDED" && job.result_entity_type === "video_composition_enhancement_artifact" && Number.isInteger(job.result_entity_id) && (job.result_entity_id ?? 0) > 0 ? job.result_entity_id : null;
}

export function shouldPollEnhancement(job: ExecutionJob): boolean {
  return job.status === "QUEUED" || job.status === "RUNNING";
}

export async function pollExactEnhancementJob(options: {
  identity: EnhancementIdentity;
  current: () => EnhancementIdentity | null;
  read: (jobId: number, signal: AbortSignal) => Promise<ExecutionJob>;
  update: (job: ExecutionJob) => void;
  temporaryFailure: () => void;
  delay?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}): Promise<void> {
  const wait = options.delay ?? ((milliseconds, signal) => new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
  }));
  while (isCurrentEnhancementOperation(options.identity, options.current())) {
    await wait(1500, options.identity.controller.signal);
    if (!isCurrentEnhancementOperation(options.identity, options.current())) return;
    try {
      const job = await options.read(options.identity.jobId, options.identity.controller.signal);
      if (!isCurrentEnhancementOperation(options.identity, options.current())) return;
      options.update(job);
      if (!shouldPollEnhancement(job)) return;
    } catch {
      if (!isCurrentEnhancementOperation(options.identity, options.current())) return;
      options.temporaryFailure();
    }
  }
}
