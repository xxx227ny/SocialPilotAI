import { useEffect, useRef, useState } from "react";

import {
  controlBatchVideoJob,
  createBatchVideo,
  getBatchVideoJob,
  listBatchVideoVariants,
  preflightBatchVideo,
} from "../../api/batchVideoJobs";
import { listProducts } from "../../api/products";
import { useReadResource } from "../../hooks/useReadResource";
import type {
  BatchPlatform,
  BatchVideoCreateResult,
  BatchVideoRequest,
} from "../../types/batchVideo";
import {
  abortBatchOperation,
  beginBatchOperation,
  controlBatchWorkflow,
  createBatchWorkflow,
  downstreamCostLabel,
  expandedVariantCount,
  finishBatchOperation,
  isCurrentBatchOperation,
  pollBatchSerial,
  recoverExactBatchWorkflow,
  type BatchOperation,
  type BatchOperationSlot,
  type BatchWorkflowApi,
} from "./batchVideoJobState";
const ALL_PLATFORMS: BatchPlatform[] = ["youtube", "tiktok", "instagram"];

const BATCH_STATUS_LABELS: Record<string, string> = {
  WAITING: "等待编排",
  RUNNING: "正在编排",
  READY_FOR_SCRIPT: "等待生成脚本",
  PAUSED: "已暂停",
  FAILED: "失败",
  CANCELLED: "已取消",
};

const workflowApi: BatchWorkflowApi = {
  preflight: preflightBatchVideo,
  create: createBatchVideo,
  readBatch: getBatchVideoJob,
  readVariants: listBatchVideoVariants,
  control: controlBatchVideoJob,
};

export function BatchVideoJobPanel() {
  const productList = useReadResource("products", listProducts);
  const products = productList.data ?? [];
  const [productIds, setProductIds] = useState<number[]>([]);
  const [platforms, setPlatforms] = useState<BatchPlatform[]>(ALL_PLATFORMS);
  const [variantsPerPlatform, setVariantsPerPlatform] = useState(1);
  const [maxConcurrency, setMaxConcurrency] = useState(3);
  const [batchIdInput, setBatchIdInput] = useState("");
  const [result, setResult] = useState<BatchVideoCreateResult | null>(null);
  const [message, setMessage] = useState("");
  const slot = useRef<BatchOperationSlot>({ current: null });
  const pollController = useRef<AbortController | null>(null);
  const sequence = useRef(0);

  useEffect(() => () => {
    abortBatchOperation(slot.current);
    pollController.current?.abort();
  }, []);

  useEffect(() => {
    if (productList.loadedAt === null || productList.loading || productList.error) return;
    setProductIds((current) => current.filter((id) => products.some((item) => item.id === id)));
  }, [productList.loadedAt, productList.loading, productList.error, products]);

  useEffect(() => {
    if (!result) return;
    const exactProductIds = [
      ...new Set(result.variants.map((item) => item.product_id)),
    ];
    if (exactProductIds.length !== 1) return;
    window.localStorage.setItem(
      `socialpilot.scriptBatch.${exactProductIds[0]}`,
      String(result.batch.id),
    );
  }, [result]);

  const total = expandedVariantCount(productIds, platforms, variantsPerPlatform);
  const request = (): BatchVideoRequest => ({
    product_ids: productIds,
    platforms,
    variants_per_platform: variantsPerPlatform,
    duration_seconds: 15,
    aspect_ratio: "9:16",
    language: "zh-CN",
    priority: 50,
    max_concurrency: maxConcurrency,
    creative_angle: null,
    idempotency_key: `content-studio-${productIds.join("-")}-${platforms.join("-")}-${variantsPerPlatform}`,
  });

  const start = (batchId: number | null) => {
    const operation: BatchOperation = {
      id: ++sequence.current,
      batchId,
      controller: new AbortController(),
    };
    return beginBatchOperation(slot.current, operation) ? operation : null;
  };

  const startPolling = (batchId: number) => {
    pollController.current?.abort();
    const controller = new AbortController();
    pollController.current = controller;
    void pollBatchSerial({
      batchId,
      signal: controller.signal,
      delay: (signal) =>
        new Promise<void>((resolve) => {
          const timer = window.setTimeout(resolve, 1000);
          signal.addEventListener(
            "abort",
            () => {
              window.clearTimeout(timer);
              resolve();
            },
            { once: true },
          );
        }),
      read: (id, signal) => recoverExactBatchWorkflow(workflowApi, id, signal),
      update: ({ batch, variants }) => setResult({ batch, variants, reused: true }),
      failure: () => setMessage("Backend连接中断；已停止轮询，未假定任务状态。"),
    });
  };

  const submit = async () => {
    const operation = start(null);
    if (!operation) return;
    setMessage("正在执行 Provider-free Preflight…");
    try {
      const data = request();
      const created = await createBatchWorkflow(workflowApi, data, operation.controller.signal);
      if (!isCurrentBatchOperation(operation, slot.current.current)) return;
      setResult(created);
      setBatchIdInput(String(created.batch.id));
      setMessage(created.reused ? "已恢复完全相同的Batch。" : "Batch与变体已原子创建。 ");
      startPolling(created.batch.id);
    } catch {
      if (!operation.controller.signal.aborted) setMessage("Backend请求失败；结果未被假定为成功。请按精确Batch ID恢复。");
    } finally {
      finishBatchOperation(slot.current, operation);
    }
  };

  const refresh = async () => {
    const batchId = Number(batchIdInput);
    if (!Number.isInteger(batchId) || batchId <= 0) return;
    const operation = start(batchId);
    if (!operation) return;
    try {
      const { batch, variants } = await recoverExactBatchWorkflow(
        workflowApi,
        batchId,
        operation.controller.signal,
      );
      if (isCurrentBatchOperation(operation, slot.current.current)) {
        setResult({ batch, variants, reused: true });
        setMessage("已按精确Batch ID恢复。 ");
        startPolling(batch.id);
      }
    } catch {
      if (!operation.controller.signal.aborted) setMessage("无法恢复该精确Batch ID。 ");
    } finally {
      finishBatchOperation(slot.current, operation);
    }
  };

  const control = async (action: "pause" | "resume" | "cancel") => {
    if (!result) return;
    const operation = start(result.batch.id);
    if (!operation) return;
    try {
      const { batch, variants } = await controlBatchWorkflow(
        workflowApi,
        result.batch.id,
        action,
        operation.controller.signal,
      );
      if (isCurrentBatchOperation(operation, slot.current.current)) {
        setResult({ batch, variants, reused: true });
        if (action === "resume") startPolling(batch.id);
      }
    } catch {
      if (!operation.controller.signal.aborted) setMessage("批量控制失败；没有假定状态已改变。 ");
    } finally {
      finishBatchOperation(slot.current, operation);
    }
  };

  return (
    <section className="batch-video-panel">
      <header><span>STAGE 3C · PROVIDER-FREE</span><h2>批量视频任务编排</h2></header>
      <p>当前阶段编排成本：0 USD（orchestration_only）。脚本、素材、TTS、渲染与发布成本{downstreamCostLabel(result?.batch.downstream_provider_cost_status ?? "NOT_ESTIMATED")}。</p>
      <div className="batch-video-panel__grid">
        <fieldset><legend>商品（可多选）</legend>{products.map((product) => (
          <label key={product.id}><input type="checkbox" checked={productIds.includes(product.id)} onChange={(event) => setProductIds((value) => event.target.checked ? [...value, product.id] : value.filter((id) => id !== product.id))} />{product.name} · BrandKitVersion {product.brand_kit_version_id ?? "未绑定"}</label>
        ))}{productList.loadedAt === null ? <p role="status">正在首次读取商品……</p> : null}{productList.error ? <button type="button" onClick={productList.refresh}>重新读取商品</button> : null}</fieldset>
        <fieldset><legend>平台</legend>{ALL_PLATFORMS.map((platform) => (
          <label key={platform}><input type="checkbox" checked={platforms.includes(platform)} onChange={(event) => setPlatforms((value) => event.target.checked ? [...value, platform] : value.filter((item) => item !== platform))} />{platform}</label>
        ))}</fieldset>
        <label>每平台变体数<input type="number" min="1" max="10" value={variantsPerPlatform} onChange={(event) => setVariantsPerPlatform(Number(event.target.value))} /></label>
        <label>最大并发<input type="number" min="1" max="20" value={maxConcurrency} onChange={(event) => setMaxConcurrency(Number(event.target.value))} /></label>
      </div>
      <p><strong>{total}</strong> 个独立变体 · 15秒 · 9:16 · zh-CN</p>
      <div className="batch-video-panel__actions"><button disabled={total === 0} onClick={() => void submit()}>Preflight并创建</button><input aria-label="精确Batch ID" value={batchIdInput} onChange={(event) => setBatchIdInput(event.target.value)} /><button onClick={() => void refresh()}>按ID恢复</button></div>
      {message && <p role="status">{message}</p>}
      {result && <><div className="batch-video-panel__actions"><button onClick={() => void control("pause")}>暂停</button><button onClick={() => void control("resume")}>恢复</button><button onClick={() => void control("cancel")}>取消</button></div><p>普通用户无需逐个平台填写脚本；“等待生成脚本”表示变体已准备好，但脚本尚未创建。请前往“一键商品视频”，系统会自动生成并激活三平台脚本。</p><table><thead><tr><th>ID</th><th>商品</th><th>平台</th><th>变体</th><th>状态</th></tr></thead><tbody>{result.variants.map((variant) => <tr key={variant.id}><td>{variant.id}</td><td>{variant.product_id}</td><td>{variant.platform}</td><td>{variant.variant_index}</td><td>{BATCH_STATUS_LABELS[variant.status] ?? variant.status}</td></tr>)}</tbody></table></>}
    </section>
  );
}
