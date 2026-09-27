import { useEffect, useRef, useState } from "react";

import {
  controlBatchVideoJob,
  createBatchVideo,
  getBatchVideoJob,
  getProductVideoWorkflowContext,
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
import { productDisplayNumber } from "../../types/product";
import {
  abortBatchOperation,
  beginBatchOperation,
  clampBatchConcurrency,
  controlBatchWorkflow,
  createBatchWorkflow,
  downstreamCostLabel,
  expandedVariantCount,
  finishBatchOperation,
  isCurrentBatchOperation,
  newBatchIdempotencyKey,
  pollBatchSerial,
  recoverExactBatchWorkflow,
  type BatchOperation,
  type BatchOperationSlot,
  type BatchWorkflowApi,
} from "./batchVideoJobState";
const ALL_PLATFORMS: BatchPlatform[] = ["youtube", "tiktok", "instagram"];

const PLATFORM_LABELS: Record<BatchPlatform, string> = {
  youtube: "YouTube Shorts",
  tiktok: "TikTok",
  instagram: "Instagram Reels",
};

const BATCH_STATUS_LABELS: Record<string, string> = {
  WAITING: "等待编排",
  RUNNING: "正在编排",
  READY_FOR_SCRIPT: "等待生成脚本",
  PAUSED: "已暂停",
  FAILED: "失败",
  CANCELLED: "已取消",
  PARTIAL_FAILED: "部分失败",
  MIXED_TERMINAL: "已结束（结果不完整）",
};

const TERMINAL_BATCH_STATUSES = new Set([
  "READY_FOR_SCRIPT",
  "FAILED",
  "CANCELLED",
  "PARTIAL_FAILED",
  "MIXED_TERMINAL",
]);

function formatBatchTime(value: string | undefined) {
  if (!value) return "时间不可用";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间不可用";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

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
  const [loadingLatest, setLoadingLatest] = useState(false);
  const slot = useRef<BatchOperationSlot>({ current: null });
  const pollController = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const total = expandedVariantCount(productIds, platforms, variantsPerPlatform);
  const selectedProduct = productIds.length === 1
    ? products.find((item) => item.id === productIds[0]) ?? null
    : null;

  useEffect(() => () => {
    abortBatchOperation(slot.current);
    pollController.current?.abort();
  }, []);

  useEffect(() => {
    if (productList.loadedAt === null || productList.loading || productList.error) return;
    setProductIds((current) => current.filter((id) => products.some((item) => item.id === id)));
  }, [productList.loadedAt, productList.loading, productList.error, products]);

  useEffect(() => {
    setMaxConcurrency((current) => clampBatchConcurrency(current, total));
  }, [total]);

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

  const request = (): BatchVideoRequest => ({
    product_ids: productIds,
    platforms,
    variants_per_platform: variantsPerPlatform,
    duration_seconds: 15,
    aspect_ratio: "9:16",
    language: "zh-CN",
    priority: 50,
    max_concurrency: clampBatchConcurrency(maxConcurrency, total),
    creative_angle: null,
    idempotency_key: newBatchIdempotencyKey(),
    reuse_identical: false,
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
      setMessage(
        created.reused
          ? "已加载本次创建请求对应的脚本批次。"
          : "已创建全新脚本批次，系统正在准备各平台任务。",
      );
      startPolling(created.batch.id);
    } catch {
      if (!operation.controller.signal.aborted) {
        setMessage("创建请求未完成。请先按所选商品加载最近脚本批次，避免重复创建。");
      }
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
        setBatchIdInput(String(batch.id));
        setMessage("已加载指定脚本批次。 ");
        startPolling(batch.id);
      }
    } catch {
      if (!operation.controller.signal.aborted) {
        setMessage("找不到该脚本批次，或它不属于当前账号。请检查脚本批次编号。 ");
      }
    } finally {
      finishBatchOperation(slot.current, operation);
    }
  };

  const loadLatestForSelectedProduct = async () => {
    if (!selectedProduct) {
      setMessage("请只选择一个商品，系统才能准确找到它最近的脚本批次。");
      return;
    }
    const operation = start(null);
    if (!operation) return;
    setLoadingLatest(true);
    setMessage(`正在查找“${selectedProduct.name}”最近可用的脚本批次……`);
    try {
      const context = await getProductVideoWorkflowContext(
        selectedProduct.id,
        operation.controller.signal,
      );
      if (!context.batch_id) {
        setResult(null);
        setBatchIdInput("");
        setMessage("这个商品还没有可用的三平台脚本批次，请创建全新脚本批次。");
        return;
      }
      const { batch, variants } = await recoverExactBatchWorkflow(
        workflowApi,
        context.batch_id,
        operation.controller.signal,
      );
      if (!isCurrentBatchOperation(operation, slot.current.current)) return;
      setResult({ batch, variants, reused: true });
      setBatchIdInput(String(batch.id));
      setMessage(`已加载“${selectedProduct.name}”最近可用的脚本批次。`);
      startPolling(batch.id);
    } catch {
      if (!operation.controller.signal.aborted) {
        setMessage("最近脚本批次读取失败，没有创建新任务，也不会产生模型费用。");
      }
    } finally {
      setLoadingLatest(false);
      finishBatchOperation(slot.current, operation);
    }
  };

  const control = async (action: "pause" | "resume" | "cancel") => {
    if (!result) return;
    if (
      action === "cancel" &&
      !window.confirm("确定取消当前脚本批次吗？取消后不能继续推进这个批次，但不会删除已有结果。")
    ) {
      return;
    }
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
        setMessage(
          action === "pause"
            ? "当前脚本批次已暂停。"
            : action === "resume"
              ? "当前脚本批次已继续。"
              : "当前脚本批次已取消；已有结果仍然保留。",
        );
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
      <header>
        <span>脚本准备区 · 本步骤不调用付费模型</span>
        <h2>批量准备平台脚本</h2>
        <p>这里创建的是供“一键商品视频”使用的脚本批次，不是最终成片批次。普通使用无需记忆任何编号。</p>
      </header>
      <div className="batch-video-panel__notice">
        <strong>编号已经简化</strong>
        <span>商品可以保留多个历史脚本批次，系统会按所选商品寻找最近可用批次；平台任务编号和脚本版本编号仅在技术排查时显示。</span>
      </div>
      <div className="batch-video-panel__grid">
        <fieldset><legend>商品（可多选）</legend>{products.map((product) => (
          <label key={product.id}><input type="checkbox" checked={productIds.includes(product.id)} onChange={(event) => setProductIds((value) => event.target.checked ? [...value, product.id] : value.filter((id) => id !== product.id))} /><span><strong>{product.name}</strong><small>商品编号 {productDisplayNumber(product)} · 品牌规范{product.brand_kit_version_id ? "已绑定" : "未绑定"}</small></span></label>
        ))}{productList.loadedAt === null ? <p role="status">正在首次读取商品……</p> : null}{productList.error ? <button type="button" onClick={productList.refresh}>重新读取商品</button> : null}</fieldset>
        <fieldset><legend>平台</legend>{ALL_PLATFORMS.map((platform) => (
          <label key={platform}><input type="checkbox" checked={platforms.includes(platform)} onChange={(event) => setPlatforms((value) => event.target.checked ? [...value, platform] : value.filter((item) => item !== platform))} />{PLATFORM_LABELS[platform]}</label>
        ))}</fieldset>
        <label>每个平台准备几套方案<input type="number" min="1" max="10" value={variantsPerPlatform} onChange={(event) => setVariantsPerPlatform(Number(event.target.value))} /></label>
        <label>同时处理数量<input type="number" min="1" max={Math.max(1, Math.min(20, total))} value={maxConcurrency} onChange={(event) => setMaxConcurrency(clampBatchConcurrency(Number(event.target.value), total))} /></label>
      </div>
      <p className="batch-video-panel__summary"><strong>{total}</strong> 个平台方案 · 每条 15 秒 · 竖屏 9:16 · 中文</p>
      <div className="batch-video-panel__primary-actions">
        <button disabled={total === 0} onClick={() => void submit()}>创建全新脚本批次</button>
        <button type="button" disabled={!selectedProduct || loadingLatest} onClick={() => void loadLatestForSelectedProduct()}>
          {loadingLatest ? "正在查找……" : "加载所选商品最近批次"}
        </button>
      </div>
      {!selectedProduct && productIds.length > 1 ? <p className="batch-video-panel__helper">“加载最近批次”一次只对应一个商品；创建新批次仍支持同时选择多个商品。</p> : null}
      <details className="batch-video-panel__advanced-recovery">
        <summary>高级：按脚本批次编号加载</summary>
        <div>
          <label>脚本批次编号<input inputMode="numeric" aria-label="脚本批次编号" placeholder="例如 7" value={batchIdInput} onChange={(event) => setBatchIdInput(event.target.value)} /></label>
          <button type="button" disabled={!batchIdInput.trim()} onClick={() => void refresh()}>加载指定脚本批次</button>
        </div>
        <small>这里只接受“脚本批次编号”，不是商品编号、平台任务编号、脚本版本编号或成片生产批次编号。</small>
      </details>
      {message && <p role="status">{message}</p>}
      {result && <section className="batch-video-panel__current">
        <header>
          <div><small>当前加载的脚本批次</small><h3>{[...new Set(result.variants.map((item) => products.find((product) => product.id === item.product_id)?.name ?? "商品记录不可用"))].join("、")}</h3></div>
          <div><strong>{BATCH_STATUS_LABELS[result.batch.status] ?? result.batch.status}</strong><small>创建于 {formatBatchTime(result.batch.created_at)}</small></div>
        </header>
        <div className="batch-video-panel__actions">
          <button disabled={result.batch.status !== "RUNNING" && result.batch.status !== "WAITING"} onClick={() => void control("pause")}>暂停批次</button>
          <button disabled={result.batch.status !== "PAUSED"} onClick={() => void control("resume")}>继续批次</button>
          <button className="batch-video-panel__danger" disabled={TERMINAL_BATCH_STATUSES.has(result.batch.status)} onClick={() => void control("cancel")}>取消批次</button>
        </div>
        <p>“等待生成脚本”表示平台方案已经准备好。前往“一键商品视频”后，系统会自动生成并激活所需脚本。</p>
        <table><thead><tr><th>商品</th><th>平台</th><th>方案</th><th>脚本</th><th>状态</th></tr></thead><tbody>{result.variants.map((variant) => { const product = products.find((item) => item.id === variant.product_id); return <tr key={variant.id}><td>{product?.name ?? "商品记录不可用"}</td><td>{PLATFORM_LABELS[variant.platform]}</td><td>第 {variant.variant_index} 套</td><td>{variant.active_script_version_id ? "已生成" : "尚未生成"}</td><td>{BATCH_STATUS_LABELS[variant.status] ?? variant.status}</td></tr>; })}</tbody></table>
        <details className="batch-video-panel__technical-ids">
          <summary>技术编号（仅排查问题时使用）</summary>
          <p>脚本批次编号：{result.batch.id}</p>
          <ul>{result.variants.map((variant) => <li key={variant.id}>{PLATFORM_LABELS[variant.platform]}：平台任务编号 {variant.id}；脚本版本编号 {variant.active_script_version_id ?? "尚未生成"}</li>)}</ul>
          <p>当前步骤成本 0 USD；后续脚本、素材、TTS、渲染与发布成本{downstreamCostLabel(result.batch.downstream_provider_cost_status)}。</p>
        </details>
      </section>}
    </section>
  );
}
