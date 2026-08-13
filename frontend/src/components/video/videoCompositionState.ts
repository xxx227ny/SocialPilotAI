import type { ExecutionJob } from "../../types/execution";

export interface CompositionIdentity {
  productId: number;
  videoProjectId: number;
  selectionDigest: string;
  jobId: number | null;
  resultArtifactId: number | null;
  operationId: number;
  controller: AbortController;
}

export function isCurrentCompositionOperation(expected: CompositionIdentity, current: CompositionIdentity | null): boolean {
  return current !== null && !expected.controller.signal.aborted && expected.productId === current.productId && expected.videoProjectId === current.videoProjectId && expected.selectionDigest === current.selectionDigest && expected.jobId === current.jobId && expected.resultArtifactId === current.resultArtifactId && expected.operationId === current.operationId && expected.controller === current.controller;
}

export function selectionIdentity(values: Record<number, number>): string {
  return Object.entries(values).sort(([a], [b]) => Number(a) - Number(b)).map(([scene, artifact]) => `${scene}:${artifact}`).join("|");
}

export function exactCompositionResult(job: ExecutionJob): number | null {
  return job.status === "SUCCEEDED" && job.result_entity_type === "video_composition_artifact" && Number.isInteger(job.result_entity_id) && (job.result_entity_id ?? 0) > 0 ? job.result_entity_id : null;
}

export function shouldPollComposition(job: ExecutionJob): boolean {
  return job.status === "QUEUED" || job.status === "RUNNING";
}

export function canReleaseCompositionLock(expected: CompositionIdentity, current: CompositionIdentity | null): boolean {
  return isCurrentCompositionOperation(expected, current);
}
