import { useCallback, useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  enqueueCopyJob,
  getCopyExecutionJob,
  getCopyPreflight,
  getExactCopyMatrix,
  listCopyJobs,
  retryCopyExecutionJob,
} from "../../api/copies";
import { copyExecutionEnabled } from "../../config/features";
import type { CopyPreflight, PersistedCopyMatrix } from "../../types/copy";
import type { ExecutionJob } from "../../types/execution";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";
import type { MarketingStrategy } from "../../types/strategy";
import {
  copyJobAllowsExplicitRetry,
  copyJobNeedsPolling,
  exactCopyResultId,
  selectExactCopyJob,
} from "./copyQueueState";

type LoadState = "loading" | "ready" | "blocked" | "error";
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
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [preflight, setPreflight] = useState<CopyPreflight | null>(null);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [matrix, setMatrix] = useState<PersistedCopyMatrix | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [reused, setReused] = useState(false);
  const [message, setMessage] = useState("");
  const controllerRef = useRef<AbortController | null>(null);
  const submitLockRef = useRef(false);
  const retryLockRef = useRef(false);
  const contextRef = useRef({
    taskId: task.id,
    productId: product.id,
    strategyId: strategy.id,
  });
  contextRef.current = {
    taskId: task.id,
    productId: product.id,
    strategyId: strategy.id,
  };

  const isCurrent = useCallback(
    (
      taskId: number,
      productId: number,
      strategyId: number,
      controller: AbortController,
    ) => {
      const current = contextRef.current;
      return (
        !controller.signal.aborted &&
        current.taskId === taskId &&
        current.productId === productId &&
        current.strategyId === strategyId
      );
    },
    [],
  );

  const loadPreflightAndHistory = useCallback(async () => {
    const taskId = task.id;
    const productId = product.id;
    const strategyId = strategy.id;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    submitLockRef.current = false;
    retryLockRef.current = false;
    setLoadState("loading");
    setMessage("");
    setPreflight(null);
    setJob(null);
    setMatrix(null);
    setReused(false);
    setAcknowledged(false);

    try {
      const currentPreflight = await getCopyPreflight(
        taskId,
        strategyId,
        controller.signal,
      );
      if (
        !isCurrent(taskId, productId, strategyId, controller) ||
        currentPreflight.task_id !== taskId ||
        currentPreflight.product_id !== productId ||
        currentPreflight.strategy_id !== strategyId
      ) {
        return;
      }
      setPreflight(currentPreflight);
      setLoadState(currentPreflight.ready_for_execution ? "ready" : "blocked");

      const jobs = await listCopyJobs(strategyId, controller.signal);
      if (!isCurrent(taskId, productId, strategyId, controller)) return;
      const restored = selectExactCopyJob(
        jobs,
        taskId,
        productId,
        strategyId,
        currentPreflight.input_digest,
      );
      setJob(restored);
      if (restored) setReused(true);
    } catch (error) {
      if (!controller.signal.aborted) {
        setMessage(getApiErrorMessage(error, "Copy队列状态读取失败，请重试。"));
        setLoadState("error");
      }
    }
  }, [isCurrent, product.id, strategy.id, task.id]);

  useEffect(() => {
    void loadPreflightAndHistory();
    return () => controllerRef.current?.abort();
  }, [loadPreflightAndHistory]);

  useEffect(() => {
    if (!copyJobNeedsPolling(job)) return;
    const jobId = job?.id;
    if (jobId === undefined) return;
    let cancelled = false;
    const context = { ...contextRef.current };
    const timer = window.setInterval(() => {
      void getCopyExecutionJob(jobId)
        .then((next) => {
          const current = contextRef.current;
          if (
            !cancelled &&
            current.taskId === context.taskId &&
            current.productId === context.productId &&
            current.strategyId === context.strategyId
          ) {
            setJob(next);
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setMessage(
              getApiErrorMessage(error, "任务状态读取失败；不会自动重新提交。"),
            );
          }
        });
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job]);

  useEffect(() => {
    const copyMatrixId = exactCopyResultId(job);
    if (copyMatrixId === null) {
      if (job?.status !== "SUCCEEDED") setMatrix(null);
      return;
    }
    const controller = new AbortController();
    void getExactCopyMatrix(
      task.id,
      strategy.id,
      copyMatrixId,
      controller.signal,
    )
      .then((result) => {
        if (
          result.id === copyMatrixId &&
          result.product_id === product.id &&
          result.marketing_strategy_id === strategy.id &&
          contextRef.current.taskId === task.id
        ) {
          setMatrix(result);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMessage(
            getApiErrorMessage(error, "精确Copy结果读取失败；未使用latest回退。"),
          );
        }
      });
    return () => controller.abort();
  }, [job, product.id, strategy.id, task.id]);

  const canEnqueue = Boolean(
    copyExecutionEnabled &&
      loadState === "ready" &&
      preflight?.ready_for_execution &&
      acknowledged &&
      job === null,
  );

  async function enqueue() {
    if (!canEnqueue || !preflight || submitLockRef.current) return;
    submitLockRef.current = true;
    setMessage("");
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const created = await enqueueCopyJob(
        task.id,
        strategy.id,
        {
          product_id: product.id,
          strategy_id: strategy.id,
          input_digest: preflight.input_digest,
          preflight_digest: preflight.preflight_digest,
          preflight_expires_at: preflight.expires_at,
          cost_confirmed: true,
        },
        controller.signal,
      );
      setJob(created.job);
      setReused(created.reused);
    } catch (error) {
      if (!controller.signal.aborted) {
        setMessage(
          getApiErrorMessage(
            error,
            "Copy任务入队失败；Provider未在本次HTTP请求中调用。",
          ),
        );
      }
    } finally {
      submitLockRef.current = false;
    }
  }

  async function retryFailedJob() {
    if (!copyJobAllowsExplicitRetry(job) || !job || retryLockRef.current) return;
    retryLockRef.current = true;
    setMessage("");
    try {
      setJob(await retryCopyExecutionJob(job.id));
    } catch (error) {
      setMessage(getApiErrorMessage(error, "任务重试入队失败。"));
    } finally {
      retryLockRef.current = false;
    }
  }

  return (
    <section className="copy-preflight" aria-label="Copy Queue Operation">
      <div className="copy-preflight__heading">
        <div>
          <p className="eyebrow">Copy Queue · Provider-safe HTTP</p>
          <h5>Qwen Copy Matrix生成任务</h5>
        </div>
        <span className={`strategy-preflight__status strategy-preflight__status--${loadState}`}>
          {loadState === "loading" ? "读取中" : loadState === "ready" ? "可入队" : loadState === "blocked" ? "未就绪" : "读取失败"}
        </span>
      </div>

      <p className="copy-preflight__intro">
        HTTP只验证精确Product、MarketingBrief、Strategy与冻结输入；只有Worker Claim后才调用Qwen。
      </p>
      <dl className="product-detail__facts copy-preflight__context">
        <div><dt>Product</dt><dd>#{product.id} · {product.name}</dd></div>
        <div><dt>MarketingBrief</dt><dd>#{task.id}</dd></div>
        <div><dt>Strategy</dt><dd>#{strategy.id}</dd></div>
        <div><dt>Strategy来源</dt><dd>{strategySource === "direct" ? "队列精确结果" : "兼容来源"}</dd></div>
        <div><dt>Brief平台</dt><dd>{task.platforms.join("、")}</dd></div>
      </dl>

      {preflight ? (
        <div className="copy-preflight__result">
          <dl className="product-detail__facts">
            <div><dt>冻结Digest</dt><dd>{preflight.input_digest.slice(0, 12)}…</dd></div>
            <div><dt>Preflight有效期</dt><dd>{new Date(preflight.expires_at).toLocaleString()}</dd></div>
            <div><dt>Provider配置</dt><dd>{preflight.provider_configured ? "已配置" : "未配置"}</dd></div>
            <div><dt>执行契约</dt><dd>{preflight.contract_ready ? "已实现" : "尚未实现"}</dd></div>
            <div><dt>预算估算</dt><dd>{preflight.estimated_cost} {preflight.currency}</dd></div>
            <div><dt>自动重试</dt><dd>禁止（单次Provider提交）</dd></div>
          </dl>
          {preflight.missing_requirements.length > 0 ? (
            <div className="strategy-preflight__missing">
              <strong>仍缺少：</strong>
              <ul>{preflight.missing_requirements.map((item) => <li key={item}>{REQUIREMENT_LABELS[item] ?? item}</li>)}</ul>
            </div>
          ) : null}
          <p className="copy-preflight__boundary">{preflight.association_notice}</p>
          <p className="strategy-execution-gate">{preflight.cost_notice}</p>
          {!job ? (
            <>
              <label className="strategy-preflight__acknowledgement">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  disabled={!preflight.ready_for_execution}
                />
                我确认任务被Worker Claim后将调用一次Qwen，预算估算为
                {preflight.estimated_cost} {preflight.currency}，并可能产生费用。
              </label>
              <button type="button" className="button" onClick={() => void enqueue()} disabled={!canEnqueue}>
                创建Copy生成任务
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      {loadState === "error" ? (
        <button type="button" className="button button--secondary" onClick={() => void loadPreflightAndHistory()}>
          重新读取
        </button>
      ) : null}
      {message ? <p className="form-feedback form-feedback--error" role="alert">{message}</p> : null}

      {job ? (
        <article className="strategy-operation-result" aria-live="polite">
          <div className="strategy-operation-result__header">
            <div><p className="eyebrow">{reused ? "已恢复/复用" : "本次新建"}</p><h5>ExecutionJob #{job.id}</h5></div>
            <span>{job.status}</span>
          </div>
          <dl className="product-detail__facts">
            <div><dt>尝试次数</dt><dd>{job.attempt_count} / {job.max_attempts}</dd></div>
            <div><dt>冻结Digest</dt><dd>{job.input_digest.slice(0, 12)}…</dd></div>
            <div><dt>安全错误码</dt><dd>{job.safe_error_code ?? "无"}</dd></div>
          </dl>
          {job.status === "QUEUED" ? <p role="status">任务已排队，等待Worker Claim。</p> : null}
          {job.status === "RUNNING" ? <p role="status">Worker正在执行；页面只轮询本地任务状态。</p> : null}
          {job.status === "FAILED" ? (
            <div className="strategy-operation-issue" role="alert">
              <strong>任务确定失败</strong>
              <p>不会自动重试。确认原因已修复后，可由用户显式重试。</p>
              {copyJobAllowsExplicitRetry(job) ? (
                <button type="button" className="button button--secondary" onClick={() => void retryFailedJob()}>
                  显式重试
                </button>
              ) : null}
            </div>
          ) : null}
          {job.status === "SUBMIT_UNKNOWN" ? (
            <div className="strategy-operation-issue" role="alert">
              <strong>提交结果不确定</strong>
              <p>可能已发生外部提交，禁止自动或页面重试。</p>
            </div>
          ) : null}
        </article>
      ) : null}

      {matrix ? <CopyMatrixResult matrix={matrix} product={product} taskId={task.id} /> : null}
      <p className="strategy-preflight__note">
        Copy生成不代表自动发布；精确结果由ExecutionJob result_entity_id恢复，未使用latest。
      </p>
    </section>
  );
}

function CopyMatrixResult({
  matrix,
  product,
  taskId,
}: {
  matrix: PersistedCopyMatrix;
  product: Product;
  taskId: number;
}) {
  return (
    <article className="copy-operation-result" aria-live="polite">
      <header>
        <div><p className="eyebrow">队列精确结果</p><h6>平台文案结果</h6></div>
        <span>CopyMatrix #{matrix.id}</span>
      </header>
      <dl className="product-detail__facts">
        <div><dt>Product</dt><dd>#{matrix.product_id} · {product.name}</dd></div>
        <div><dt>MarketingBrief</dt><dd>#{taskId}</dd></div>
        <div><dt>Strategy</dt><dd>#{matrix.marketing_strategy_id}</dd></div>
        <div><dt>生成平台</dt><dd>{matrix.copies.map((copy) => copy.platform).join("、")}</dd></div>
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
    </article>
  );
}
