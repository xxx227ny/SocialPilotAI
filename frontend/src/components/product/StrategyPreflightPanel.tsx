import { useEffect, useRef, useState } from "react";

import {
  classifyStrategyExecutionError,
  generateMarketingStrategy,
  getLatestMarketingStrategy,
  getStrategyPreflight,
} from "../../api/strategies";
import { strategyExecutionEnabled } from "../../config/features";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";
import type {
  MarketingStrategy,
  StrategyExecutionIssue,
  StrategyPreflight,
} from "../../types/strategy";

type PreflightState = "idle" | "checking" | "ready" | "blocked" | "failed";
type ExecutionState =
  | "idle"
  | "submitting"
  | "succeeded"
  | "failed"
  | "recovering"
  | "recovered";
type ResultSource = "direct" | "latest";

const REQUIREMENT_LABELS: Record<string, string> = {
  product_name: "商品名称",
  product_category: "商品分类",
  product_description: "商品描述",
  product_selling_points: "商品卖点",
  target_market_snapshot: "目标市场快照",
  supported_platforms: "受支持的平台",
  audience: "受众（任务默认配置）",
  language: "语言（任务默认配置）",
  tone: "语气（任务默认配置）",
  objective: "目标（任务默认配置）",
  qwen_provider_type: "Qwen Provider 可用性",
  provider_configuration: "Provider 配置",
};

interface StrategyPreflightPanelProps {
  task: MarketingTask;
  product: Product;
}

export function StrategyPreflightPanel({
  task,
  product,
}: StrategyPreflightPanelProps) {
  const [preflightState, setPreflightState] = useState<PreflightState>("idle");
  const [preflight, setPreflight] = useState<StrategyPreflight | null>(null);
  const [preflightError, setPreflightError] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [executionState, setExecutionState] = useState<ExecutionState>("idle");
  const [executionIssue, setExecutionIssue] =
    useState<StrategyExecutionIssue | null>(null);
  const [strategy, setStrategy] = useState<MarketingStrategy | null>(null);
  const [resultSource, setResultSource] = useState<ResultSource | null>(null);

  const preflightControllerRef = useRef<AbortController | null>(null);
  const executionControllerRef = useRef<AbortController | null>(null);
  const contextRequestIdRef = useRef(0);
  const executionLockRef = useRef(false);
  const activeContextRef = useRef({ taskId: task.id, productId: product.id });
  activeContextRef.current = { taskId: task.id, productId: product.id };

  useEffect(() => {
    const requestId = ++contextRequestIdRef.current;
    const controller = new AbortController();
    preflightControllerRef.current?.abort();
    executionControllerRef.current?.abort();
    executionControllerRef.current = controller;
    executionLockRef.current = false;
    setPreflightState("idle");
    setPreflight(null);
    setPreflightError("");
    setAcknowledged(false);
    setExecutionState("recovering");
    setExecutionIssue(null);
    setStrategy(null);
    setResultSource(null);

    void getLatestMarketingStrategy(product.id, controller.signal)
      .then((latest) => {
        if (!isCurrent(requestId, task.id, product.id, controller)) return;
        setStrategy(latest);
        setResultSource("latest");
        setExecutionState("recovered");
      })
      .catch(() => {
        if (!isCurrent(requestId, task.id, product.id, controller)) return;
        setExecutionState("idle");
      });

    return () => controller.abort();
  }, [task.id, product.id]);

  function isCurrent(
    requestId: number,
    taskId: number,
    productId: number,
    controller: AbortController,
  ) {
    const active = activeContextRef.current;
    return (
      !controller.signal.aborted &&
      requestId === contextRequestIdRef.current &&
      active.taskId === taskId &&
      active.productId === productId
    );
  }

  async function runPreflight() {
    if (preflightState === "checking" || executionLockRef.current) return;
    const taskId = task.id;
    const productId = product.id;
    const requestId = ++contextRequestIdRef.current;
    const controller = new AbortController();
    preflightControllerRef.current?.abort();
    preflightControllerRef.current = controller;
    setPreflightState("checking");
    setPreflight(null);
    setPreflightError("");
    setAcknowledged(false);
    setExecutionIssue(null);

    try {
      const result = await getStrategyPreflight(taskId, controller.signal);
      if (
        !isCurrent(requestId, taskId, productId, controller) ||
        result.task_id !== taskId ||
        result.product_id !== productId
      ) {
        return;
      }
      setPreflight(result);
      setPreflightState(result.ready ? "ready" : "blocked");
    } catch {
      if (!isCurrent(requestId, taskId, productId, controller)) return;
      setPreflightError("生成前检查失败，请重试。");
      setPreflightState("failed");
    }
  }

  const canExecute = Boolean(
    strategyExecutionEnabled &&
      preflightState === "ready" &&
      preflight?.ready &&
      preflight.provider_configured &&
      preflight.task_id === task.id &&
      preflight.product_id === product.id &&
      acknowledged &&
      executionState !== "submitting" &&
      executionState !== "recovering",
  );

  async function executeStrategyGeneration() {
    if (executionLockRef.current || !canExecute || !preflight) return;
    if (
      !strategyExecutionEnabled ||
      !acknowledged ||
      !preflight.ready ||
      !preflight.provider_configured ||
      preflight.task_id !== task.id ||
      preflight.product_id !== product.id
    ) {
      return;
    }

    const taskId = task.id;
    const productId = product.id;
    const requestId = ++contextRequestIdRef.current;
    const controller = new AbortController();
    executionControllerRef.current?.abort();
    executionControllerRef.current = controller;
    executionLockRef.current = true;
    setExecutionState("submitting");
    setExecutionIssue(null);

    try {
      const created = await generateMarketingStrategy(productId, controller.signal);
      if (!isCurrent(requestId, taskId, productId, controller)) return;
      setStrategy(created);
      setResultSource("direct");
      setExecutionState("succeeded");
    } catch (error) {
      if (!isCurrent(requestId, taskId, productId, controller)) return;
      const issue = classifyStrategyExecutionError(error);
      setExecutionState("recovering");
      try {
        const latest = await getLatestMarketingStrategy(productId, controller.signal);
        if (!isCurrent(requestId, taskId, productId, controller)) return;
        setStrategy(latest);
        setResultSource("latest");
        setExecutionState("recovered");
      } catch {
        if (!isCurrent(requestId, taskId, productId, controller)) return;
        setExecutionIssue(issue);
        setExecutionState("failed");
      }
    } finally {
      if (requestId === contextRequestIdRef.current) {
        executionLockRef.current = false;
      }
    }
  }

  return (
    <section className="strategy-preflight" aria-labelledby="strategy-operation-title">
      <div className="strategy-preflight__heading">
        <div>
          <p className="eyebrow">V2-C2.1 · Strategy Operation</p>
          <h4 id="strategy-operation-title">策略生成状态与结果</h4>
        </div>
        <span className={`strategy-preflight__status strategy-preflight__status--${preflightState}`}>
          {preflightState === "checking" ? "检查中" : preflightState === "ready" ? "已就绪" : preflightState === "blocked" ? "未就绪" : preflightState === "failed" ? "检查失败" : "待检查"}
        </span>
      </div>

      <p className="strategy-preflight__intro">
        先执行只读检查，再由用户确认可能产生 Provider 费用。策略执行在生产构建中默认关闭。
      </p>

      <button className="button button--secondary" type="button" onClick={() => void runPreflight()} disabled={preflightState === "checking" || executionLockRef.current}>
        {preflightState === "checking" ? "正在检查…" : preflightState === "failed" ? "重试生成前检查" : "运行生成前检查"}
      </button>

      {preflightError ? <p className="form-feedback form-feedback--error" role="alert">{preflightError}</p> : null}

      {preflight ? (
        <div className="strategy-preflight__result">
          <dl className="product-detail__facts">
            <div><dt>任务</dt><dd>#{preflight.task_id}</dd></div>
            <div><dt>Provider</dt><dd>{preflight.provider_label} / {preflight.model_label}</dd></div>
            <div><dt>安全配置</dt><dd>{preflight.provider_configured ? "已配置" : "未配置"}</dd></div>
          </dl>
          {preflight.missing_requirements.length > 0 ? (
            <div className="strategy-preflight__missing"><strong>仍缺少：</strong><ul>{preflight.missing_requirements.map((item) => <li key={item}>{REQUIREMENT_LABELS[item] ?? item}</li>)}</ul></div>
          ) : null}
          <p className="strategy-execution-gate">{preflight.cost_notice}</p>
          <label className="strategy-preflight__acknowledgement">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} disabled={!preflight.ready || !preflight.provider_configured || executionLockRef.current} />
            我理解真实执行可能调用 Provider 并产生费用。
          </label>
          <button className="button" type="button" onClick={() => void executeStrategyGeneration()} disabled={!canExecute}>
            {executionState === "submitting" ? "正在调用 Qwen…" : executionState === "recovering" ? "正在核对结果…" : "调用 Qwen 生成策略"}
          </button>
          {!strategyExecutionEnabled ? <p className="strategy-preflight__note">当前构建未开放真实策略执行；按钮保持禁用。</p> : null}
        </div>
      ) : null}

      {executionState === "submitting" ? <p className="strategy-operation-progress" role="status">请求已提交，正在等待 Provider 返回，请勿重复操作。</p> : null}
      {executionState === "recovering" ? <p className="strategy-operation-progress" role="status">正在读取该商品最近一次已保存策略，以核对不确定响应。</p> : null}
      {executionState === "failed" && executionIssue ? (
        <div className={`strategy-operation-issue strategy-operation-issue--${executionIssue.category}`} role="alert">
          <strong>策略生成失败 · {executionIssue.category}</strong>
          <p>{executionIssue.message}</p>
          {executionIssue.retryable ? <button className="button button--secondary" type="button" onClick={() => void executeStrategyGeneration()} disabled={!canExecute}>重试策略生成</button> : null}
        </div>
      ) : null}

      {strategy ? <StrategyResult strategy={strategy} product={product} source={resultSource ?? "latest"} /> : executionState === "idle" ? <p className="strategy-preflight__note">当前商品尚无可展示的已保存策略。</p> : null}
    </section>
  );
}

function StrategyResult({ strategy, product, source }: { strategy: MarketingStrategy; product: Product; source: ResultSource }) {
  return (
    <article className="strategy-operation-result" aria-live="polite">
      <div className="strategy-operation-result__header">
        <div><p className="eyebrow">{source === "direct" ? "本次生成策略" : "商品最新策略 · Backend已保存记录"}</p><h5>营销策略结果</h5></div>
        <span>Strategy #{strategy.id}</span>
      </div>
      <dl className="product-detail__facts">
        <div><dt>商品</dt><dd>#{strategy.product_id} · {product.name}</dd></div>
        <div><dt>创建时间</dt><dd>{new Date(strategy.created_at).toLocaleString()}</dd></div>
      </dl>
      <section><h6>定位</h6><p>{strategy.positioning}</p></section>
      <StrategyList title="受众洞察" items={strategy.audience_insights} />
      <StrategyList title="营销角度" items={strategy.angles} />
      <StrategyList title="内容支柱 / 证据" items={strategy.evidence} />
      <StrategyList title="风险与边界" items={strategy.risks} warning />
      <p className="strategy-operation-result__boundary">当前策略按商品关联，尚未与本次MarketingBrief建立直接版本关系。</p>
    </article>
  );
}

function StrategyList({ title, items, warning = false }: { title: string; items: string[]; warning?: boolean }) {
  return <section className={warning ? "strategy-operation-list strategy-operation-list--warning" : "strategy-operation-list"}><h6>{title}</h6><ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></section>;
}
