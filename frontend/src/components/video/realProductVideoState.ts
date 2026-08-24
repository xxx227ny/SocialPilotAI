import type { ExecutionJob } from "../../types/execution";
import type { ProductVideoSource } from "../../types/productMarketingVideo";

const PLATFORM_ORDER = ["tiktok", "youtube", "instagram"] as const;

export function selectThreePlatformSources(
  sources: ProductVideoSource[],
): ProductVideoSource[] {
  return PLATFORM_ORDER.map((platform) =>
    sources.find((source) => source.platform === platform),
  ).filter((source): source is ProductVideoSource => source !== undefined);
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
