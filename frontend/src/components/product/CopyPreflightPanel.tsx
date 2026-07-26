import { useEffect, useRef, useState } from "react";

import { getCopyPreflight } from "../../api/copies";
import { copyExecutionEnabled } from "../../config/features";
import type { CopyPreflight } from "../../types/copy";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";
import type { MarketingStrategy } from "../../types/strategy";

type CopyPreflightState =
  | "idle"
  | "checking"
  | "ready"
  | "blocked"
  | "failed";
type StrategySource = "direct" | "latest";

const REQUIREMENT_LABELS: Record<string, string> = {
  product_name: "商品名称",
  product_category: "商品分类",
  product_description: "商品描述",
  product_selling_points: "商品卖点",
  target_market_snapshot: "MarketingBrief目标市场快照",
  supported_platforms: "MarketingBrief支持平台",
  strategy_schema: "Strategy内容完整性",
  provider_configuration: "Qwen Provider配置",
  copy_execution: "Backend Copy执行授权",
  brief_aware_exact_strategy_copy_contract:
    "Brief-aware、精确Strategy Copy执行契约（V2-C2.2B）",
};

interface CopyPreflightPanelProps {
  task: MarketingTask;
  product: Product;
  strategy: MarketingStrategy;
  strategySource: StrategySource;
}

export function CopyPreflightPanel({
  task,
  product,
  strategy,
  strategySource,
}: CopyPreflightPanelProps) {
  const [state, setState] = useState<CopyPreflightState>("idle");
  const [preflight, setPreflight] = useState<CopyPreflight | null>(null);
  const [error, setError] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const requestLockRef = useRef(false);
  const activeContextRef = useRef({
    productId: product.id,
    taskId: task.id,
    strategyId: strategy.id,
  });
  activeContextRef.current = {
    productId: product.id,
    taskId: task.id,
    strategyId: strategy.id,
  };

  useEffect(() => {
    ++requestIdRef.current;
    controllerRef.current?.abort();
    controllerRef.current = null;
    requestLockRef.current = false;
    setState("idle");
    setPreflight(null);
    setError("");
    setAcknowledged(false);
    return () => controllerRef.current?.abort();
  }, [product.id, task.id, strategy.id, strategySource]);

  function isCurrent(
    requestId: number,
    controller: AbortController,
    productId: number,
    taskId: number,
    strategyId: number,
  ) {
    const active = activeContextRef.current;
    return (
      !controller.signal.aborted &&
      requestId === requestIdRef.current &&
      active.productId === productId &&
      active.taskId === taskId &&
      active.strategyId === strategyId
    );
  }

  async function runCopyPreflight() {
    if (requestLockRef.current) return;
    const productId = product.id;
    const taskId = task.id;
    const strategyId = strategy.id;
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    requestLockRef.current = true;
    setState("checking");
    setPreflight(null);
    setError("");
    setAcknowledged(false);

    try {
      const result = await getCopyPreflight(taskId, strategyId, controller.signal);
      if (
        !isCurrent(
          requestId,
          controller,
          productId,
          taskId,
          strategyId,
        ) ||
        result.product_id !== productId ||
        result.task_id !== taskId ||
        result.strategy_id !== strategyId
      ) {
        return;
      }
      setPreflight(result);
      setState(result.ready_for_execution ? "ready" : "blocked");
    } catch {
      if (
        !isCurrent(
          requestId,
          controller,
          productId,
          taskId,
          strategyId,
        )
      ) {
        return;
      }
      setError("Copy生成前检查失败，请检查Backend连接后重试。");
      setState("failed");
    } finally {
      if (requestId === requestIdRef.current) {
        requestLockRef.current = false;
      }
    }
  }

  return (
    <section className="copy-preflight" aria-labelledby="copy-operation-title">
      <div className="copy-preflight__heading">
        <div>
          <p className="eyebrow">V2-C2.2A · COPY OPERATION ENTRY</p>
          <h5 id="copy-operation-title">Copy Matrix生成前安全检查</h5>
        </div>
        <span
          className={`strategy-preflight__status strategy-preflight__status--${state}`}
        >
          {state === "checking"
            ? "检查中"
            : state === "ready"
              ? "已就绪"
              : state === "blocked"
                ? "契约未就绪"
                : state === "failed"
                  ? "检查失败"
                  : "待检查"}
        </span>
      </div>

      <p className="copy-preflight__intro">
        本阶段只读取精确MarketingBrief与Strategy并运行Preflight，不调用AI、不创建CopyMatrix。
      </p>

      <dl className="product-detail__facts copy-preflight__context">
        <div><dt>商品</dt><dd>#{product.id} · {product.name}</dd></div>
        <div><dt>MarketingBrief</dt><dd>#{task.id}</dd></div>
        <div><dt>Strategy</dt><dd>#{strategy.id}</dd></div>
        <div>
          <dt>Strategy来源</dt>
          <dd>{strategySource === "direct" ? "本次生成策略" : "商品最新策略"}</dd>
        </div>
        <div><dt>目标市场快照</dt><dd>{task.target_markets.join("、")}</dd></div>
        <div><dt>Brief平台</dt><dd>{task.platforms.join("、")}</dd></div>
      </dl>

      <p className="copy-preflight__boundary">
        {strategySource === "latest"
          ? "这是商品最新Strategy，无法证明它属于当前MarketingBrief。"
          : "本次响应显示该Strategy来自当前MarketingBrief，但该Brief关联没有持久化。"}
        CopyMatrix真实模型可关联精确Strategy，但不保存MarketingBrief ID。
      </p>

      <button
        className="button button--secondary"
        type="button"
        onClick={() => void runCopyPreflight()}
        disabled={state === "checking"}
      >
        {state === "checking"
          ? "正在检查…"
          : state === "failed"
            ? "重试Copy生成前检查"
            : "运行Copy生成前检查"}
      </button>

      {error ? (
        <p className="form-feedback form-feedback--error" role="alert">
          {error}
        </p>
      ) : null}

      {preflight ? (
        <div className="copy-preflight__result">
          <dl className="product-detail__facts">
            <div>
              <dt>Provider配置</dt>
              <dd>{preflight.provider_configured ? "已配置" : "未配置"}</dd>
            </div>
            <div>
              <dt>Backend Copy开关</dt>
              <dd>{preflight.execution_enabled ? "已开启" : "默认关闭"}</dd>
            </div>
            <div>
              <dt>精确输入</dt>
              <dd>{preflight.input_ready ? "完整" : "不完整"}</dd>
            </div>
            <div>
              <dt>执行契约</dt>
              <dd>{preflight.contract_ready ? "已就绪" : "尚未就绪"}</dd>
            </div>
          </dl>

          {preflight.missing_requirements.length > 0 ? (
            <div className="strategy-preflight__missing">
              <strong>仍缺少：</strong>
              <ul>
                {preflight.missing_requirements.map((item) => (
                  <li key={item}>{REQUIREMENT_LABELS[item] ?? item}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className="copy-preflight__boundary">
            {preflight.association_notice}
          </p>
          <p className="strategy-execution-gate">{preflight.cost_notice}</p>

          <label className="strategy-preflight__acknowledgement">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              disabled={!preflight.input_ready}
            />
            我理解真实Copy生成会调用阿里云百炼Qwen，并可能消耗比赛Credits。
          </label>

          <button
            className="button"
            type="button"
            disabled
            title="V2-C2.2B完成Brief-aware精确Strategy执行契约后开放"
          >
            调用Qwen生成Copy Matrix
          </button>

          <p className="strategy-preflight__note">
            V2-C2.2B完成契约后开放；本按钮没有执行handler，勾选费用确认也不会触发调用。
          </p>
          {!copyExecutionEnabled ? (
            <p className="strategy-preflight__note">
              当前Frontend构建未开放Copy执行。
            </p>
          ) : null}
          <p className="strategy-preflight__note">
            Copy生成不代表自动发布，也不代表已获得TikTok、Instagram或Facebook账号授权。
          </p>
        </div>
      ) : null}
    </section>
  );
}
