import { useEffect, useRef, useState } from "react";

import {
  classifyCopyExecutionError,
  generateTaskBoundCopyMatrix,
  getCopyPreflight,
  getLatestCopyForStrategy,
  isCopyNotFound,
} from "../../api/copies";
import { copyExecutionEnabled } from "../../config/features";
import type {
  CopyExecutionIssue,
  CopyPreflight,
  PersistedCopyMatrix,
} from "../../types/copy";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";
import type { MarketingStrategy } from "../../types/strategy";

type CopyOperationState =
  | "idle"
  | "checking"
  | "ready"
  | "blocked"
  | "submitting"
  | "succeeded"
  | "failed"
  | "recovering"
  | "recovered";
type StrategySource = "direct" | "latest";
type CopyResultSource = "direct" | "latest";

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
  const [state, setState] = useState<CopyOperationState>("idle");
  const [preflight, setPreflight] = useState<CopyPreflight | null>(null);
  const [preflightError, setPreflightError] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [matrix, setMatrix] = useState<PersistedCopyMatrix | null>(null);
  const [resultSource, setResultSource] =
    useState<CopyResultSource | null>(null);
  const [sourceTaskId, setSourceTaskId] = useState<number | null>(null);
  const [associationNotice, setAssociationNotice] = useState("");
  const [issue, setIssue] = useState<CopyExecutionIssue | null>(null);

  const preflightControllerRef = useRef<AbortController | null>(null);
  const executionControllerRef = useRef<AbortController | null>(null);
  const contextRequestIdRef = useRef(0);
  const preflightRequestIdRef = useRef(0);
  const executionRequestIdRef = useRef(0);
  const executionLockRef = useRef(false);
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
    const contextRequestId = ++contextRequestIdRef.current;
    ++preflightRequestIdRef.current;
    ++executionRequestIdRef.current;
    const controller = new AbortController();
    preflightControllerRef.current?.abort();
    executionControllerRef.current?.abort();
    executionControllerRef.current = controller;
    executionLockRef.current = false;
    setState("recovering");
    setPreflight(null);
    setPreflightError("");
    setAcknowledged(false);
    setMatrix(null);
    setResultSource(null);
    setSourceTaskId(null);
    setAssociationNotice("");
    setIssue(null);

    void getLatestCopyForStrategy(strategy.id, controller.signal)
      .then((latest) => {
        if (
          !isCurrentContext(
            contextRequestId,
            product.id,
            task.id,
            strategy.id,
            controller,
          ) ||
          latest.product_id !== product.id ||
          latest.marketing_strategy_id !== strategy.id
        ) {
          return;
        }
        setMatrix(latest);
        setResultSource("latest");
        setState("recovered");
      })
      .catch((error: unknown) => {
        if (
          !isCurrentContext(
            contextRequestId,
            product.id,
            task.id,
            strategy.id,
            controller,
          )
        ) {
          return;
        }
        if (isCopyNotFound(error)) {
          setState("idle");
          return;
        }
        setIssue(classifyCopyExecutionError(error));
        setState("failed");
      });

    return () => controller.abort();
  }, [product.id, task.id, strategy.id, strategySource]);

  function isCurrentContext(
    contextRequestId: number,
    productId: number,
    taskId: number,
    strategyId: number,
    controller: AbortController,
  ) {
    const active = activeContextRef.current;
    return (
      !controller.signal.aborted &&
      contextRequestId === contextRequestIdRef.current &&
      active.productId === productId &&
      active.taskId === taskId &&
      active.strategyId === strategyId
    );
  }

  async function runCopyPreflight() {
    if (state === "checking" || executionLockRef.current) return;
    const productId = product.id;
    const taskId = task.id;
    const strategyId = strategy.id;
    const contextRequestId = contextRequestIdRef.current;
    const requestId = ++preflightRequestIdRef.current;
    const controller = new AbortController();
    preflightControllerRef.current?.abort();
    preflightControllerRef.current = controller;
    setState("checking");
    setPreflight(null);
    setPreflightError("");
    setAcknowledged(false);
    setIssue(null);

    try {
      const result = await getCopyPreflight(
        taskId,
        strategyId,
        controller.signal,
      );
      if (
        !isCurrentContext(
          contextRequestId,
          productId,
          taskId,
          strategyId,
          controller,
        ) ||
        requestId !== preflightRequestIdRef.current ||
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
        !isCurrentContext(
          contextRequestId,
          productId,
          taskId,
          strategyId,
          controller,
        ) ||
        requestId !== preflightRequestIdRef.current
      ) {
        return;
      }
      setPreflightError("Copy生成前检查失败，请检查Backend连接后重试。");
      setState("failed");
    }
  }

  const canExecute = Boolean(
    copyExecutionEnabled &&
      (state === "ready" || state === "failed") &&
      preflight?.ready &&
      preflight.input_ready &&
      preflight.provider_configured &&
      preflight.execution_enabled &&
      preflight.contract_ready &&
      preflight.ready_for_execution &&
      preflight.product_id === product.id &&
      preflight.task_id === task.id &&
      preflight.strategy_id === strategy.id &&
      acknowledged &&
      !executionLockRef.current,
  );

  async function executeCopyGeneration() {
    if (executionLockRef.current || !canExecute || !preflight) return;
    if (
      !copyExecutionEnabled ||
      !acknowledged ||
      !preflight.ready ||
      !preflight.input_ready ||
      !preflight.provider_configured ||
      !preflight.execution_enabled ||
      !preflight.contract_ready ||
      !preflight.ready_for_execution ||
      preflight.product_id !== product.id ||
      preflight.task_id !== task.id ||
      preflight.strategy_id !== strategy.id
    ) {
      return;
    }

    const productId = product.id;
    const taskId = task.id;
    const strategyId = strategy.id;
    const previousMatrixId = matrix?.id ?? null;
    const contextRequestId = contextRequestIdRef.current;
    const requestId = ++executionRequestIdRef.current;
    const controller = new AbortController();
    executionControllerRef.current?.abort();
    executionControllerRef.current = controller;
    executionLockRef.current = true;
    setState("submitting");
    setIssue(null);
    setPreflightError("");

    try {
      const created = await generateTaskBoundCopyMatrix(
        taskId,
        strategyId,
        controller.signal,
      );
      if (
        !isCurrentContext(
          contextRequestId,
          productId,
          taskId,
          strategyId,
          controller,
        ) ||
        requestId !== executionRequestIdRef.current ||
        created.source_task_id !== taskId ||
        created.source_strategy_id !== strategyId ||
        created.source_product_id !== productId ||
        created.copy_matrix.marketing_strategy_id !== strategyId ||
        created.copy_matrix.product_id !== productId
      ) {
        return;
      }
      setMatrix(created.copy_matrix);
      setResultSource("direct");
      setSourceTaskId(created.source_task_id);
      setAssociationNotice(created.association_notice);
      setAcknowledged(false);
      setState("succeeded");
    } catch (error) {
      if (
        !isCurrentContext(
          contextRequestId,
          productId,
          taskId,
          strategyId,
          controller,
        ) ||
        requestId !== executionRequestIdRef.current
      ) {
        return;
      }
      const failure = classifyCopyExecutionError(error);
      if (
        failure.category !== "network" &&
        failure.category !== "backend" &&
        failure.category !== "unknown"
      ) {
        setIssue(failure);
        setState("failed");
        return;
      }

      setState("recovering");
      try {
        const latest = await getLatestCopyForStrategy(
          strategyId,
          controller.signal,
        );
        if (
          !isCurrentContext(
            contextRequestId,
            productId,
            taskId,
            strategyId,
            controller,
          ) ||
          requestId !== executionRequestIdRef.current
        ) {
          return;
        }
        if (
          latest.product_id === productId &&
          latest.marketing_strategy_id === strategyId &&
          latest.id !== previousMatrixId
        ) {
          setMatrix(latest);
          setResultSource("latest");
          setSourceTaskId(null);
          setAssociationNotice("");
          setState("recovered");
          return;
        }
        setIssue(failure);
        setState("failed");
      } catch {
        if (
          !isCurrentContext(
            contextRequestId,
            productId,
            taskId,
            strategyId,
            controller,
          ) ||
          requestId !== executionRequestIdRef.current
        ) {
          return;
        }
        setIssue(failure);
        setState("failed");
      }
    } finally {
      if (requestId === executionRequestIdRef.current) {
        executionLockRef.current = false;
      }
    }
  }

  return (
    <section className="copy-preflight" aria-labelledby="copy-operation-title">
      <div className="copy-preflight__heading">
        <div>
          <p className="eyebrow">V2-C2.2B · EXACT COPY CONTRACT</p>
          <h5 id="copy-operation-title">Copy Matrix执行与恢复</h5>
        </div>
        <span
          className={`strategy-preflight__status strategy-preflight__status--${state}`}
        >
          {copyStateLabel(state)}
        </span>
      </div>

      <p className="copy-preflight__intro">
        精确使用当前MarketingBrief、Strategy及Brief平台快照；生产构建默认关闭真实执行。
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
        CopyMatrix会持久化精确Strategy关联；MarketingBrief关联仅存在于本次执行响应，因为数据表没有MarketingBrief外键。
      </p>

      <button
        className="button button--secondary"
        type="button"
        onClick={() => void runCopyPreflight()}
        disabled={state === "checking" || executionLockRef.current}
      >
        {state === "checking"
          ? "正在检查…"
          : preflightError
            ? "重试Copy生成前检查"
            : "运行Copy生成前检查"}
      </button>

      {preflightError ? (
        <p className="form-feedback form-feedback--error" role="alert">
          {preflightError}
        </p>
      ) : null}

      {preflight ? (
        <div className="copy-preflight__result">
          <dl className="product-detail__facts">
            <div><dt>Provider配置</dt><dd>{preflight.provider_configured ? "已配置" : "未配置"}</dd></div>
            <div><dt>Backend Copy开关</dt><dd>{preflight.execution_enabled ? "已开启" : "默认关闭"}</dd></div>
            <div><dt>精确输入</dt><dd>{preflight.input_ready ? "完整" : "不完整"}</dd></div>
            <div><dt>执行契约</dt><dd>{preflight.contract_ready ? "已实现" : "尚未实现"}</dd></div>
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
              disabled={
                !preflight.input_ready ||
                !preflight.provider_configured ||
                !preflight.execution_enabled ||
                !preflight.contract_ready ||
                executionLockRef.current
              }
            />
            我理解真实Copy生成会调用Provider，并可能消耗比赛Credits。
          </label>

          <button
            className="button"
            type="button"
            onClick={() => void executeCopyGeneration()}
            disabled={!canExecute}
          >
            {state === "submitting"
              ? "正在调用Qwen…"
              : state === "recovering"
                ? "正在核对结果…"
                : "调用Qwen生成Copy Matrix"}
          </button>

          {!copyExecutionEnabled ? (
            <p className="strategy-preflight__note">
              当前Frontend构建未开放Copy执行；按钮保持禁用。
            </p>
          ) : null}
          {!preflight.execution_enabled ? (
            <p className="strategy-preflight__note">
              Backend尚未授权Copy执行。
            </p>
          ) : null}
        </div>
      ) : null}

      {state === "submitting" ? (
        <p className="strategy-operation-progress" role="status">
          请求已提交，正在等待Provider返回，请勿重复操作。
        </p>
      ) : null}
      {state === "recovering" ? (
        <p className="strategy-operation-progress" role="status">
          正在按精确Strategy读取最新Copy Matrix，以恢复页面或核对不确定响应。
        </p>
      ) : null}
      {state === "failed" && issue ? (
        <div
          className={`strategy-operation-issue strategy-operation-issue--${issue.category}`}
          role="alert"
        >
          <strong>Copy生成失败 · {issue.category}</strong>
          <p>{issue.message}</p>
          {issue.retryable ? (
            <button
              className="button button--secondary"
              type="button"
              onClick={() => void executeCopyGeneration()}
              disabled={!canExecute}
            >
              重试Copy生成
            </button>
          ) : null}
        </div>
      ) : null}

      {matrix ? (
        <CopyMatrixResult
          matrix={matrix}
          product={product}
          source={resultSource ?? "latest"}
          sourceTaskId={sourceTaskId}
          associationNotice={associationNotice}
        />
      ) : state === "idle" ? (
        <p className="strategy-preflight__note">
          当前Strategy尚无已保存Copy Matrix。请先运行Preflight。
        </p>
      ) : null}

      <p className="strategy-preflight__note">
        Copy生成不代表自动发布，也不代表已获得TikTok、Instagram或Facebook账号授权。
      </p>
    </section>
  );
}

function copyStateLabel(state: CopyOperationState) {
  const labels: Record<CopyOperationState, string> = {
    idle: "待检查",
    checking: "检查中",
    ready: "已就绪",
    blocked: "执行未开放",
    submitting: "生成中",
    succeeded: "本次生成成功",
    failed: "操作失败",
    recovering: "恢复中",
    recovered: "已恢复",
  };
  return labels[state];
}

function CopyMatrixResult({
  matrix,
  product,
  source,
  sourceTaskId,
  associationNotice,
}: {
  matrix: PersistedCopyMatrix;
  product: Product;
  source: CopyResultSource;
  sourceTaskId: number | null;
  associationNotice: string;
}) {
  return (
    <article className="copy-operation-result" aria-live="polite">
      <header>
        <div>
          <p className="eyebrow">
            {source === "direct"
              ? "本次生成Copy Matrix"
              : "该策略最新Copy Matrix"}
          </p>
          <h6>平台文案结果</h6>
        </div>
        <span>CopyMatrix #{matrix.id}</span>
      </header>

      <dl className="product-detail__facts">
        <div><dt>Product</dt><dd>#{matrix.product_id} · {product.name}</dd></div>
        <div><dt>Strategy</dt><dd>#{matrix.marketing_strategy_id}</dd></div>
        {source === "direct" && sourceTaskId !== null ? (
          <div><dt>本次响应Brief</dt><dd>#{sourceTaskId}</dd></div>
        ) : null}
        <div><dt>生成平台</dt><dd>{matrix.copies.map((copy) => copy.platform).join("、")}</dd></div>
        <div><dt>创建时间</dt><dd>{new Date(matrix.created_at).toLocaleString()}</dd></div>
        <div><dt>数据来源</dt><dd>Backend已保存CopyMatrix</dd></div>
      </dl>

      <div className="copy-operation-result__platforms">
        {matrix.copies.map((copy) => (
          <section key={copy.platform}>
            <h6>{copy.platform}</h6>
            <dl>
              <div><dt>Hook</dt><dd>{copy.hook}</dd></div>
              <div><dt>Caption</dt><dd>{copy.caption}</dd></div>
              <div><dt>Hashtags</dt><dd>{copy.hashtags.join(" ")}</dd></div>
              <div><dt>CTA</dt><dd>{copy.cta}</dd></div>
            </dl>
          </section>
        ))}
      </div>

      <p className="copy-preflight__boundary">
        Strategy关联已通过marketing_strategy_id持久化。
        {source === "direct"
          ? "本次响应记录了所示MarketingBrief，但该Brief关联未持久化。"
          : "这是该Strategy的最新Copy Matrix，不能证明它属于当前MarketingBrief。"}
      </p>
      {source === "direct" && associationNotice ? (
        <p className="strategy-preflight__note">{associationNotice}</p>
      ) : null}
    </article>
  );
}
