import { useCallback, useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  enqueueStrategyJob,
  getExactMarketingStrategy,
  getExecutionJob,
  getStrategyPreflight,
  listStrategyJobs,
  retryExecutionJob,
} from "../../api/strategies";
import { strategyExecutionEnabled } from "../../config/features";
import type { ExecutionJob } from "../../types/execution";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";
import type {
  MarketingStrategy,
  StrategyPreflight,
} from "../../types/strategy";
import { CopyPreflightPanel } from "./CopyPreflightPanel";
import {
  exactStrategyResultId,
  jobAllowsExplicitRetry,
  jobNeedsPolling,
  selectExactStrategyJob,
} from "./strategyQueueState";
import {
  cacheEntryIsFresh,
  getStrategyWorkspaceSnapshot,
  setStrategyWorkspaceSnapshot,
} from "./copyWorkspaceCache";

type LoadState = "loading" | "ready" | "blocked" | "error";

function executionStatusLabel(status: ExecutionJob["status"]) {
  return {
    QUEUED: "排队中",
    RUNNING: "执行中",
    PAUSED: "已暂停",
    SUCCEEDED: "已完成",
    FAILED: "已失败",
    CANCELLED: "已取消",
    SUBMIT_UNKNOWN: "提交状态不确定",
  }[status];
}

const REQUIREMENT_LABELS: Record<string, string> = {
  product_name: "商品名称",
  product_category: "商品分类",
  product_description: "商品描述",
  product_selling_points: "商品卖点",
  target_market_snapshot: "目标市场快照",
  supported_platforms: "受支持的平台",
  audience: "受众",
  language: "语言",
  tone: "语气",
  objective: "目标",
  qwen_provider_type: "千问模型服务",
  provider_configuration: "模型服务配置",
  strategy_execution: "服务端执行授权",
};

interface StrategyPreflightPanelProps {
  task: MarketingTask;
  product: Product;
}

export function StrategyPreflightPanel({
  task,
  product,
}: StrategyPreflightPanelProps) {
  const initialSnapshot = getStrategyWorkspaceSnapshot(task.id, product.id);
  const [loadState, setLoadState] = useState<LoadState>(
    initialSnapshot?.value.loadState ?? "loading",
  );
  const [preflight, setPreflight] = useState<StrategyPreflight | null>(
    initialSnapshot?.value.preflight ?? null,
  );
  const [job, setJob] = useState<ExecutionJob | null>(
    initialSnapshot?.value.job ?? null,
  );
  const [strategy, setStrategy] = useState<MarketingStrategy | null>(
    initialSnapshot?.value.strategy ?? null,
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const [reused, setReused] = useState(false);
  const [message, setMessage] = useState("");
  const controllerRef = useRef<AbortController | null>(null);
  const submitLockRef = useRef(false);
  const retryLockRef = useRef(false);
  const contextRef = useRef({ taskId: task.id, productId: product.id });
  contextRef.current = { taskId: task.id, productId: product.id };

  const isCurrent = useCallback(
    (taskId: number, productId: number, controller: AbortController) => {
      const current = contextRef.current;
      return (
        !controller.signal.aborted &&
        current.taskId === taskId &&
        current.productId === productId
      );
    },
    [],
  );

  const loadPreflightAndHistory = useCallback(async () => {
    const taskId = task.id;
    const productId = product.id;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    submitLockRef.current = false;
    retryLockRef.current = false;
    setMessage("");
    setAcknowledged(false);

    const cached = getStrategyWorkspaceSnapshot(taskId, productId);
    if (cached) {
      setLoadState(cached.value.loadState);
      setPreflight(cached.value.preflight);
      setJob(cached.value.job);
      setStrategy(cached.value.strategy);
      setReused(cached.value.reused);
      if (cacheEntryIsFresh(cached)) return;
    } else {
      setLoadState("loading");
      setPreflight(null);
      setJob(null);
      setStrategy(null);
      setReused(false);
    }

    try {
      const [currentPreflight, jobs] = await Promise.all([
        getStrategyPreflight(taskId, controller.signal),
        listStrategyJobs(taskId, controller.signal),
      ]);
      if (
        !isCurrent(taskId, productId, controller) ||
        currentPreflight.task_id !== taskId ||
        currentPreflight.product_id !== productId
      ) {
        return;
      }
      const restored = selectExactStrategyJob(
        jobs,
        taskId,
        productId,
        currentPreflight.input_digest,
      );
      const strategyId = exactStrategyResultId(restored);
      const restoredStrategy = strategyId === null
        ? null
        : await getExactMarketingStrategy(taskId, strategyId, controller.signal);
      if (!isCurrent(taskId, productId, controller)) return;
      if (
        restoredStrategy &&
        (restoredStrategy.id !== strategyId || restoredStrategy.product_id !== productId)
      ) return;
      const nextLoadState = currentPreflight.ready_for_execution ? "ready" : "blocked";
      setPreflight(currentPreflight);
      setLoadState(nextLoadState);
      setJob(restored);
      setStrategy(restoredStrategy);
      setReused(restored !== null);
      setStrategyWorkspaceSnapshot(taskId, productId, {
        loadState: nextLoadState,
        preflight: currentPreflight,
        job: restored,
        strategy: restoredStrategy,
        reused: restored !== null,
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        setMessage(getApiErrorMessage(error, "策略队列状态读取失败，请重试。"));
        if (!cached) setLoadState("error");
      }
    }
  }, [isCurrent, product.id, task.id]);

  useEffect(() => {
    void loadPreflightAndHistory();
    return () => controllerRef.current?.abort();
  }, [loadPreflightAndHistory]);

  useEffect(() => {
    if (!jobNeedsPolling(job)) return;
    const jobId = job?.id;
    if (jobId === undefined) return;
    const taskId = task.id;
    const productId = product.id;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getExecutionJob(jobId)
        .then((next) => {
          if (
            cancelled ||
            contextRef.current.taskId !== taskId ||
            contextRef.current.productId !== productId
          ) {
            return;
          }
          setJob(next);
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
  }, [job, product.id, task.id]);

  useEffect(() => {
    const strategyId = exactStrategyResultId(job);
    if (strategyId === null) {
      if (job?.status !== "SUCCEEDED") setStrategy(null);
      return;
    }
    if (strategy?.id === strategyId) return;
    const controller = new AbortController();
    void getExactMarketingStrategy(task.id, strategyId, controller.signal)
      .then((result) => {
        if (
          result.id === strategyId &&
          result.product_id === product.id &&
          contextRef.current.taskId === task.id
        ) {
          setStrategy(result);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMessage(
            getApiErrorMessage(error, "精确策略结果读取失败；未使用 latest 回退。"),
          );
        }
      });
    return () => controller.abort();
  }, [job, product.id, strategy?.id, task.id]);

  useEffect(() => {
    if (
      !preflight ||
      preflight.task_id !== task.id ||
      preflight.product_id !== product.id ||
      loadState === "loading" ||
      loadState === "error"
    ) return;
    setStrategyWorkspaceSnapshot(task.id, product.id, {
      loadState,
      preflight,
      job,
      strategy,
      reused,
    });
  }, [job, loadState, preflight, product.id, reused, strategy, task.id]);

  const canEnqueue = Boolean(
    strategyExecutionEnabled &&
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
      const created = await enqueueStrategyJob(
        task.id,
        {
          product_id: product.id,
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
            "策略任务入队失败；Provider 未在本次 HTTP 请求中调用。",
          ),
        );
      }
    } finally {
      submitLockRef.current = false;
    }
  }

  async function retryFailedJob() {
    if (!jobAllowsExplicitRetry(job) || !job || retryLockRef.current) return;
    retryLockRef.current = true;
    setMessage("");
    try {
      setJob(await retryExecutionJob(job.id));
    } catch (error) {
      setMessage(getApiErrorMessage(error, "任务重试入队失败。"));
    } finally {
      retryLockRef.current = false;
    }
  }

  return (
    <section className="strategy-preflight" aria-label="营销策略生成任务">
      <div className="strategy-preflight__heading">
        <div>
          <p className="eyebrow">营销策略任务 · 安全入队</p>
          <h4>千问营销策略生成任务</h4>
        </div>
        <span className={`strategy-preflight__status strategy-preflight__status--${loadState}`}>
          {loadState === "loading"
            ? "读取中"
            : loadState === "ready"
              ? "可入队"
              : loadState === "blocked"
                ? "未就绪"
                : "读取失败"}
        </span>
      </div>

      <p className="strategy-preflight__intro">
        网页请求只验证冻结输入并创建任务；只有后台任务确认领取后才会调用千问。
      </p>

      {preflight ? (
        <div className="strategy-preflight__result">
          <dl className="product-detail__facts">
            <div><dt>商品</dt><dd>#{preflight.product_id}</dd></div>
            <div><dt>营销任务</dt><dd>#{preflight.task_id}</dd></div>
            <div><dt>冻结内容指纹</dt><dd>{preflight.input_digest.slice(0, 12)}…</dd></div>
            <div><dt>前置检查有效期</dt><dd>{new Date(preflight.expires_at).toLocaleString()}</dd></div>
            <div><dt>模型服务配置</dt><dd>{preflight.provider_configured ? "就绪" : "缺失"}</dd></div>
          </dl>
          {preflight.missing_requirements.length > 0 ? (
            <div className="strategy-preflight__missing">
              <strong>尚缺：</strong>
              <ul>
                {preflight.missing_requirements.map((item) => (
                  <li key={item}>{REQUIREMENT_LABELS[item] ?? item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="strategy-execution-gate">{preflight.cost_notice}</p>
          {!strategyExecutionEnabled ? (
            <p className="form-feedback form-feedback--error" role="status">
              当前网页构建未开启策略执行功能，请使用产品开发版或联系管理员更新前端版本。
            </p>
          ) : null}
          {!job ? (
            <>
              <label className="strategy-preflight__acknowledgement">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  disabled={!preflight.ready_for_execution}
                />
                我确认本任务被后台领取后可能调用千问并产生费用。
              </label>
              <button type="button" className="button" onClick={() => void enqueue()} disabled={!canEnqueue}>
                创建策略生成任务
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
            <div><p className="eyebrow">{reused ? "已恢复/复用" : "本次新建"}</p><h5>执行任务 #{job.id}</h5></div>
            <span>{executionStatusLabel(job.status)}</span>
          </div>
          <dl className="product-detail__facts">
            <div><dt>尝试次数</dt><dd>{job.attempt_count} / {job.max_attempts}</dd></div>
            <div><dt>冻结内容指纹</dt><dd>{job.input_digest.slice(0, 12)}…</dd></div>
            <div><dt>安全错误码</dt><dd>{job.safe_error_code ?? "无"}</dd></div>
          </dl>
          {job.status === "QUEUED" ? <p role="status">任务已排队，等待后台任务领取。</p> : null}
          {job.status === "RUNNING" ? <p role="status">后台任务正在执行；页面只查询本地任务状态。</p> : null}
          {job.status === "FAILED" ? (
            <div className="strategy-operation-issue" role="alert">
              <strong>任务确定失败</strong>
              <p>不会自动重试。确认原因已修复后，可由用户显式重试。</p>
              {jobAllowsExplicitRetry(job) ? (
                <button type="button" className="button button--secondary" onClick={() => void retryFailedJob()}>
                  显式重试
                </button>
              ) : null}
            </div>
          ) : null}
          {job.status === "SUBMIT_UNKNOWN" ? (
            <div className="strategy-operation-issue" role="alert">
              <strong>提交结果不确定</strong>
              <p>可能已经发生外部提交，禁止自动或页面重试。</p>
            </div>
          ) : null}
        </article>
      ) : null}

      {strategy ? (
        <>
          <StrategyResult strategy={strategy} product={product} taskId={task.id} />
          <CopyPreflightPanel
            task={task}
            product={product}
            strategy={strategy}
            strategySource="direct"
          />
        </>
      ) : null}
    </section>
  );
}

function StrategyResult({
  strategy,
  product,
  taskId,
}: {
  strategy: MarketingStrategy;
  product: Product;
  taskId: number;
}) {
  return (
    <article className="strategy-operation-result">
      <div className="strategy-operation-result__header">
        <div><p className="eyebrow">队列精确结果</p><h5>营销策略</h5></div>
        <span>营销策略 #{strategy.id}</span>
      </div>
      <dl className="product-detail__facts">
        <div><dt>商品</dt><dd>#{strategy.product_id} · {product.name}</dd></div>
        <div><dt>营销任务</dt><dd>#{taskId}</dd></div>
      </dl>
      <section><h6>定位</h6><p>{strategy.positioning}</p></section>
      <StrategyList title="受众洞察" items={strategy.audience_insights} />
      <StrategyList title="营销角度" items={strategy.angles} />
      <StrategyList title="证据" items={strategy.evidence} />
      <StrategyList title="风险" items={strategy.risks} />
      <p className="strategy-operation-result__boundary">
        结果通过执行任务的精确结果编号读取，不使用模糊记录回退。
      </p>
    </article>
  );
}

function StrategyList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="strategy-operation-list">
      <h6>{title}</h6>
      <ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>
    </section>
  );
}
