import type { QwenScriptJob, QwenScriptJobCreateResult, QwenScriptPreflight, QwenScriptPreflightRequest, VideoScriptActivation, VideoScriptCreateResult, VideoScriptDraft, VideoScriptPreflight, VideoScriptVersion } from "../../types/videoScriptVersion";

export interface ScriptApi {
  preflight: (variantId: number, draft: VideoScriptDraft, signal: AbortSignal) => Promise<VideoScriptPreflight>;
  create: (variantId: number, draft: VideoScriptDraft, checked: VideoScriptPreflight, signal: AbortSignal) => Promise<VideoScriptCreateResult>;
  list: (variantId: number, signal: AbortSignal) => Promise<VideoScriptVersion[]>;
  get: (variantId: number, versionId: number, signal: AbortSignal) => Promise<VideoScriptVersion>;
  activate: (variantId: number, versionId: number, signal: AbortSignal) => Promise<VideoScriptActivation>;
}
export interface ScriptOperation { id: number; variantId: number; controller: AbortController; }
export interface ScriptOperationSlot { current: ScriptOperation | null; }
export const totalSceneDurationMs = (draft: Pick<VideoScriptDraft, "scenes">) => draft.scenes.reduce((total, scene) => total + scene.end_ms - scene.start_ms, 0);
export const isScriptDurationValid = (draft: Pick<VideoScriptDraft, "scenes">) => totalSceneDurationMs(draft) === 15000;
export const sortVersionsAscending = (versions: VideoScriptVersion[]) => [...versions].sort((a, b) => a.version_number - b.version_number);
export const shouldMountVideoScriptFlow = (enabled: boolean, presentation: boolean) => enabled && !presentation;
export function isCurrentScriptOperation(operation: ScriptOperation, current: ScriptOperation | null) { return operation === current && current?.id === operation.id && current.variantId === operation.variantId; }
export function replaceScriptOperation(slot: ScriptOperationSlot, id: number, variantId: number) {
  slot.current?.controller.abort();
  const operation = { id, variantId, controller: new AbortController() };
  slot.current = operation;
  return operation;
}
export async function runLatestScriptOperation<T>(options: {
  operation: ScriptOperation;
  current: () => ScriptOperation | null;
  execute: (signal: AbortSignal) => Promise<T>;
  success: (result: T) => void;
  failure: (error: unknown) => void;
}) {
  const { operation, current, execute, success, failure } = options;
  try {
    const result = await execute(operation.controller.signal);
    if (isCurrentScriptOperation(operation, current())) success(result);
  } catch (error) {
    if (!operation.controller.signal.aborted && isCurrentScriptOperation(operation, current())) failure(error);
  }
}
export const scriptReviewLabel = (status: string) => status === "UNREVIEWED" ? "未审核" : "审核状态不可用";
export const scriptCostLabel = (scope: string) => scope === "manual_versioning_only" ? "当前阶段成本0；仅人工版本管理" : "成本范围不可用";
export async function saveScriptVersion(api: ScriptApi, variantId: number, draft: VideoScriptDraft, signal: AbortSignal) {
  if (!isScriptDurationValid(draft)) throw new Error("Storyboard duration must equal 15 seconds");
  const checked = await api.preflight(variantId, draft, signal);
  return api.create(variantId, draft, checked, signal);
}
export async function recoverExactScript(api: ScriptApi, variantId: number, activeVersionId: number | null, signal: AbortSignal) {
  const versions = sortVersionsAscending(await api.list(variantId, signal));
  const resolvedActiveId = activeVersionId ?? versions.find((item) => item.is_active)?.id ?? null;
  const active = resolvedActiveId === null ? null : await api.get(variantId, resolvedActiveId, signal);
  return { versions, active };
}
export async function activateExactScript(api: ScriptApi, variantId: number, versionId: number, signal: AbortSignal) {
  await api.activate(variantId, versionId, signal);
  return api.get(variantId, versionId, signal);
}
export function compareExactVersions(left: VideoScriptVersion, right: VideoScriptVersion) {
  return { titleChanged: left.title !== right.title, conceptChanged: left.concept !== right.concept, hookChanged: left.hook !== right.hook, ctaChanged: left.cta !== right.cta, scenesChanged: JSON.stringify(left.scenes) !== JSON.stringify(right.scenes) };
}

export interface QwenScriptApi {
  preflight: (variantId: number, request: QwenScriptPreflightRequest, signal: AbortSignal) => Promise<QwenScriptPreflight>;
  create: (variantId: number, request: QwenScriptPreflightRequest, checked: QwenScriptPreflight, signal: AbortSignal) => Promise<QwenScriptJobCreateResult>;
  readJob: (jobId: number, signal: AbortSignal) => Promise<QwenScriptJob>;
  readVersion: (variantId: number, versionId: number, signal: AbortSignal) => Promise<VideoScriptVersion>;
}
export const qwenCostLabel = (checked: QwenScriptPreflight) => checked.estimated_cost_min === null || checked.estimated_cost_max === null
  ? "费用估算尚未配置，不能入队"
  : `${checked.estimated_cost_min}–${checked.estimated_cost_max} ${checked.currency}（${checked.cost_estimate_basis}）`;
export const shouldPollQwenJob = (job: QwenScriptJob) => job.status === "QUEUED" || job.status === "RUNNING";
export const exactQwenResultVersionId = (job: QwenScriptJob) => job.status === "SUCCEEDED" && job.result_entity_type === "video_script_version" ? job.result_entity_id : null;
export async function confirmAndCreateQwenJob(api: QwenScriptApi, variantId: number, request: QwenScriptPreflightRequest, checked: QwenScriptPreflight, confirmed: boolean, signal: AbortSignal) {
  if (!confirmed) throw new Error("Qwen cost confirmation is required");
  if (!checked.ready_for_execution || checked.estimated_cost_min === null || checked.estimated_cost_max === null || checked.cost_estimate_basis === null) throw new Error("Qwen Preflight is not ready");
  return { checked, created: await api.create(variantId, request, checked, signal) };
}
export async function recoverExactQwenJob(api: QwenScriptApi, variantId: number, jobId: number, signal: AbortSignal) {
  const job = await api.readJob(jobId, signal);
  if (job.job_type !== "qwen.video_script.generate.v1" || job.source_type !== "batch_video_variant" || job.source_id !== variantId) throw new Error("Qwen Job identity mismatch");
  const versionId = exactQwenResultVersionId(job);
  const version = versionId === null ? null : await api.readVersion(variantId, versionId, signal);
  return { job, version };
}
export async function pollQwenJobSerial(options: { api: QwenScriptApi; variantId: number; jobId: number; signal: AbortSignal; delay: (signal: AbortSignal) => Promise<void>; update: (job: QwenScriptJob, version: VideoScriptVersion | null) => void; failure: () => void; }) {
  while (!options.signal.aborted) {
    try {
      const { job, version } = await recoverExactQwenJob(options.api, options.variantId, options.jobId, options.signal);
      options.update(job, version);
      if (!shouldPollQwenJob(job)) return;
      await options.delay(options.signal);
    } catch {
      if (!options.signal.aborted) options.failure();
      return;
    }
  }
}
