import { useEffect, useState } from "react";

import { listBatchVideoVariants } from "../../api/batchVideoJobs";
import type { BatchVideoVariant } from "../../types/batchVideo";
import { VideoScriptVersionPanel } from "./VideoScriptVersionPanel";

function savedBatchId(productId: number): string {
  try {
    return window.localStorage.getItem(`socialpilot.scriptBatch.${productId}`) ?? "";
  } catch {
    return "";
  }
}

export function AdvancedVideoScriptVersionPanel({
  productId,
  qwenEnabled,
}: {
  productId: number;
  qwenEnabled: boolean;
}) {
  const [batchIdInput, setBatchIdInput] = useState(() => savedBatchId(productId));
  const [variants, setVariants] = useState<BatchVideoVariant[]>([]);
  const [selectedVariantId, setSelectedVariantId] = useState<number | null>(null);
  const [message, setMessage] = useState("");

  const load = async (batchId: number, signal?: AbortSignal) => {
    try {
      const loaded = await listBatchVideoVariants(batchId, signal);
      const matching = loaded.filter((item) => item.product_id === productId);
      setVariants(matching);
      setSelectedVariantId(null);
      setMessage(
        matching.length > 0
          ? `已读取批次 #${batchId} 中当前商品的 ${matching.length} 个精确变体。`
          : "该批次不包含当前商品；未使用其他商品的变体。",
      );
    } catch {
      if (signal?.aborted) return;
      setVariants([]);
      setSelectedVariantId(null);
      setMessage("无法读取该精确批次，请检查批次编号。 ");
    }
  };

  useEffect(() => {
    const restored = savedBatchId(productId);
    setBatchIdInput(restored);
    setVariants([]);
    setSelectedVariantId(null);
    setMessage("");
    const batchId = Number(restored);
    if (!Number.isInteger(batchId) || batchId <= 0) return;
    const controller = new AbortController();
    void load(batchId, controller.signal);
    return () => controller.abort();
  }, [productId]);

  const selected = variants.find((item) => item.id === selectedVariantId) ?? null;

  return (
    <section className="video-script-panel" aria-label="脚本版本管理（高级）">
      <header>
        <span>高级工具</span>
        <h2>脚本版本管理（高级）</h2>
      </header>
      <p>普通用户无需进入这里。一键商品视频会自动生成并激活三平台脚本。</p>
      <label>
        当前商品的精确批次编号
        <input
          type="number"
          min="1"
          value={batchIdInput}
          onChange={(event) => setBatchIdInput(event.target.value)}
        />
      </label>
      <button
        type="button"
        onClick={() => {
          const batchId = Number(batchIdInput);
          if (Number.isInteger(batchId) && batchId > 0) void load(batchId);
        }}
      >
        读取精确批次变体
      </button>
      {variants.length > 0 ? (
        <label>
          选择需要管理的精确变体
          <select
            value={selectedVariantId ?? ""}
            onChange={(event) =>
              setSelectedVariantId(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">请选择变体</option>
            {variants.map((variant) => (
              <option key={variant.id} value={variant.id}>
                变体 #{variant.id} · {variant.platform} #{variant.variant_index} · {variant.status}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {message ? <p role="status">{message}</p> : null}
      {selected ? (
        <VideoScriptVersionPanel
          variant={selected}
          onClose={() => setSelectedVariantId(null)}
          qwenEnabled={qwenEnabled}
        />
      ) : null}
    </section>
  );
}
