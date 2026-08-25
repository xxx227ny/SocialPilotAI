import type { ExecutionJob } from "../../types/execution";
import type {
  BatchQwenScriptRequest,
  BatchVideoVariant,
} from "../../types/batchVideo";
import type {
  ProductVideoProductionBatch,
  ProductVideoProductionItem,
  ProductVideoSource,
} from "../../types/productMarketingVideo";

const PLATFORM_ORDER = ["tiktok", "youtube", "instagram"] as const;

const STAGE_PROGRESS: Record<ProductVideoProductionItem["stage"], number> = {
  QUEUED: 0,
  GENERATING_IMAGES: 15,
  PREPARING_VIDEO: 30,
  GENERATING_VIDEO: 45,
  COMPOSING: 65,
  GENERATING_VOICEOVER: 78,
  ENHANCING: 90,
  COMPLETE: 100,
};

const STAGE_LABELS: Record<ProductVideoProductionItem["stage"], string> = {
  QUEUED: "等待开始",
  GENERATING_IMAGES: "万象生成商品画面",
  PREPARING_VIDEO: "冻结视频方案",
  GENERATING_VIDEO: "生成商品动态视频",
  COMPOSING: "标准化视频画面",
  GENERATING_VOICEOVER: "千问生成配音",
  ENHANCING: "同步字幕并生成最终成片",
  COMPLETE: "已完成",
};

const ERROR_MESSAGES: Record<string, string> = {
  PRODUCTION_WANX_IMAGE_FAILED: "万象商品图生成失败，可保留其他平台结果后重试。",
  PRODUCTION_WANX_SUBMIT_UNKNOWN: "万象提交状态不确定，系统已停止自动重试以避免重复扣费。",
  PRODUCTION_HAPPYHORSE_SUBMIT_FAILED: "商品动态视频提交失败。",
  PRODUCTION_HAPPYHORSE_SUBMIT_UNKNOWN:
    "商品动态视频提交状态不确定，系统已停止自动重试以避免重复扣费。",
  PRODUCTION_HAPPYHORSE_REFRESH_FAILED:
    "商品动态视频结果读取遇到临时限制，可点击“重试失败平台”继续读取原任务。",
  PRODUCTION_HAPPYHORSE_REFRESH_RETRYABLE:
    "云端暂时限制结果查询；原视频任务已保留，请稍后点击“重试失败平台”。",
  PRODUCTION_HAPPYHORSE_REFRESH_LIMIT: "商品动态视频等待超时。",
  PRODUCTION_COMPOSITION_FAILED: "视频标准化合成失败。",
  PRODUCTION_VOICEOVER_FAILED: "千问配音生成失败。",
  PRODUCTION_VOICEOVER_SUBMIT_UNKNOWN:
    "千问配音提交状态不确定，系统已停止自动重试以避免重复扣费。",
  PRODUCTION_ENHANCEMENT_FAILED: "最终字幕与音频合成失败。",
  PRODUCTION_ENHANCEMENT_PERSIST_UNKNOWN: "最终成片保存状态不确定，请勿重复生成。",
};

export function productionStageLabel(item: ProductVideoProductionItem): string {
  return STAGE_LABELS[item.stage] ?? item.stage;
}

export function productionProgress(item: ProductVideoProductionItem): number {
  return STAGE_PROGRESS[item.stage] ?? 0;
}

export function productionFailureMessage(code?: string | null): string {
  if (!code) return "生成失败，请查看当前步骤后重试。";
  return ERROR_MESSAGES[code] ?? `生成失败（${code}）`;
}

export function productionBatchTerminal(
  batch: ProductVideoProductionBatch,
  items: ProductVideoProductionItem[] = [],
): boolean {
  if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(batch.status)) return true;
  return (
    batch.status === "PARTIAL_FAILED" &&
    items.length > 0 &&
    items.every((item) => ["SUCCEEDED", "FAILED", "CANCELLED"].includes(item.status))
  );
}

export function productionBatchRecoverable(
  batch: ProductVideoProductionBatch,
  items: ProductVideoProductionItem[],
): boolean {
  return (
    batch.status === "PARTIAL_FAILED" &&
    items.some(
      (item) =>
        item.status === "FAILED" &&
        [
          "PRODUCTION_HAPPYHORSE_REFRESH_FAILED",
          "PRODUCTION_HAPPYHORSE_REFRESH_RETRYABLE",
        ].includes(item.safe_error_code ?? ""),
    )
  );
}

export function productionPollDelayMs(
  items: ProductVideoProductionItem[],
): number {
  return items.some(
    (item) => item.status === "RUNNING" && item.stage === "GENERATING_VIDEO",
  )
    ? 10_000
    : 2_000;
}

export function selectThreePlatformSources(
  sources: ProductVideoSource[],
): ProductVideoSource[] {
  return PLATFORM_ORDER.map((platform) =>
    sources.find((source) => source.platform === platform),
  ).filter((source): source is ProductVideoSource => source !== undefined);
}

export function selectOneClickVariants(
  variants: BatchVideoVariant[],
  productId: number,
): BatchVideoVariant[] {
  return PLATFORM_ORDER.map((platform) =>
    variants
      .filter(
        (variant) =>
          variant.product_id === productId &&
          variant.platform === platform &&
          variant.status === "READY_FOR_SCRIPT",
      )
      .sort(
        (left, right) =>
          left.variant_index - right.variant_index || left.id - right.id,
      )[0],
  ).filter((variant): variant is BatchVideoVariant => variant !== undefined);
}

export function buildBatchQwenScriptRequest(
  variants: BatchVideoVariant[],
  productId: number,
  strategyId: number,
  copyMatrixId: number | null,
): BatchQwenScriptRequest | null {
  const selected = selectOneClickVariants(variants, productId);
  if (selected.length !== 3 || strategyId <= 0) return null;
  return {
    product_id: productId,
    variant_ids: selected.map((variant) => variant.id),
    strategy_id: strategyId,
    copy_matrix_id: copyMatrixId,
  };
}

export function buildThreePlatformPreflightPayload(
  sources: ProductVideoSource[],
  reference: { id: number; sha256?: string | null } | null,
) {
  const selected = selectThreePlatformSources(sources);
  if (selected.length !== 3 || !reference?.sha256) return null;
  return {
    reference_product_asset_id: reference.id,
    reference_product_asset_sha256: reference.sha256,
    selections: selected.map((source) => ({
      variant_id: source.variant_id,
      script_version_id: source.script_version_id,
    })),
  };
}

export class RealProductVideoOperation {
  private sequence = 0;
  private controller: AbortController | null = null;

  begin() {
    this.controller?.abort();
    this.controller = new AbortController();
    return { id: ++this.sequence, signal: this.controller.signal };
  }

  current(id: number) {
    return id === this.sequence && !this.controller?.signal.aborted;
  }

  stop() {
    this.controller?.abort();
    this.controller = null;
  }
}

export async function pollExactJob(
  job: ExecutionJob,
  read: (id: number, signal?: AbortSignal) => Promise<ExecutionJob>,
  signal: AbortSignal,
): Promise<ExecutionJob> {
  let current = job;
  while (["QUEUED", "RUNNING"].includes(current.status)) {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, 400);
      signal.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
    current = await read(current.id, signal);
  }
  return current;
}

export function requireSuccessfulResult(job: ExecutionJob, type: string): number {
  if (
    job.status !== "SUCCEEDED" ||
    job.result_entity_type !== type ||
    !job.result_entity_id
  ) {
    throw new Error(realProductVideoErrorMessage(job.safe_error_code));
  }
  return job.result_entity_id;
}

export function realProductVideoErrorMessage(code?: string | null): string {
  if (code === "VOICEOVER_EXCEEDS_TIMELINE") {
    return "旁白超过视频时间，请缩短文案后重新生成。";
  }
  return code || "生成任务未成功完成";
}
