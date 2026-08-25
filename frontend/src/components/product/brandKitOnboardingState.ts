import type {
  BrandKit,
  BrandKitVersion,
  BrandKitVersionCreateResult,
} from "../../types/brandKit";
import type { SystemReadinessResponse } from "../../types/health";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";

export interface OnboardingStep {
  id: number;
  label: string;
  complete: boolean;
}

export function findBrandKitVersion(
  brandKits: BrandKit[],
  versionId: number | null,
): BrandKitVersion | null {
  if (versionId === null) return null;
  for (const kit of brandKits) {
    const version = kit.versions.find((item) => item.id === versionId);
    if (version) return version;
  }
  return null;
}

export function automaticallySelectedVersionId(
  brandKit: BrandKit | null,
): number | null {
  return brandKit?.versions.length === 1 ? brandKit.versions[0].id : null;
}

export function mergeBrandKitVersion(
  brandKits: BrandKit[],
  brandKitId: number,
  version: BrandKitVersion,
): BrandKit[] {
  return brandKits.map((kit) =>
    kit.id !== brandKitId ||
    kit.versions.some((candidate) => candidate.id === version.id)
      ? kit
      : {
          ...kit,
          versions: [...kit.versions, version].sort(
            (left, right) => left.version_number - right.version_number,
          ),
        },
  );
}

export function versionCreationMessage(
  result: BrandKitVersionCreateResult,
): string {
  return result.reused
    ? `内容相同，已复用版本 ${result.version.version_number}`
    : `已创建版本 ${result.version.version_number}`;
}

export function deriveOnboardingSteps(
  readiness: SystemReadinessResponse | null,
  brandKits: BrandKit[],
  products: Product[],
  selectedProduct: Product | null,
  briefs: MarketingTask[],
): OnboardingStep[] {
  const runtimeReady = Boolean(
    readiness?.backend.ready && readiness.database.ready,
  );
  const brandReady = brandKits.some((kit) => kit.versions.length > 0);
  const productReady = products.length > 0;
  const bindingReady = Boolean(
    selectedProduct &&
      findBrandKitVersion(
        brandKits,
        selectedProduct.brand_kit_version_id,
      ),
  );
  const briefReady = Boolean(selectedProduct && briefs.length > 0);
  const contentReady = Boolean(
    runtimeReady &&
      brandReady &&
      productReady &&
      bindingReady &&
      briefReady &&
      readiness?.qwen.ready,
  );

  return [
    { id: 1, label: "运行环境与数据库就绪", complete: runtimeReady },
    { id: 2, label: "创建品牌规范版本 1", complete: brandReady },
    { id: 3, label: "创建商品", complete: productReady },
    {
      id: 4,
      label: "商品绑定明确的品牌规范版本",
      complete: bindingReady,
    },
    { id: 5, label: "创建营销任务", complete: briefReady },
    { id: 6, label: "内容生成准备完成", complete: contentReady },
  ];
}

export const SAFE_QWEN_CONFIGURATION_GUIDANCE =
  "内容生成尚未就绪。请在本机配置 QWEN_API_KEY；如部署要求，再配置 QWEN_WORKSPACE_ID、QWEN_ENDPOINT、QWEN_REGION 和 QWEN_MODEL。不要在网页或聊天中粘贴任何值。";

export async function runWithSynchronousRequestLock<T>(
  lock: { current: boolean },
  action: () => Promise<T>,
): Promise<T | undefined> {
  if (lock.current) return undefined;
  lock.current = true;
  try {
    return await action();
  } finally {
    lock.current = false;
  }
}
