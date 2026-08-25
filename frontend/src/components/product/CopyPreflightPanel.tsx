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
  copyMatrixCsv,
  copyMatrixText,
  copyJobAllowsExplicitRetry,
  copyJobNeedsPolling,
  exactCopyResultId,
  platformCopyText,
  selectExactCopyJob,
} from "./copyQueueState";

type LoadState = "loading" | "ready" | "blocked" | "error";
type StrategySource = "direct" | "latest";

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
  target_market_snapshot: "营销任务目标市场快照",
  supported_platforms: "营销任务支持平台",
  strategy_schema: "营销策略内容完整性",
  provider_configuration: "千问模型服务配置",
  copy_execution: "后端文案执行授权",
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
  const [regenerationRequested, setRegenerationRequested] = useState(false);
  const [regenerationAcknowledged, setRegenerationAcknowledged] = useState(false);
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
    setRegenerationRequested(false);
    setRegenerationAcknowledged(false);

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

  async function regenerate() {
    if (
      !matrix ||
      job?.status !== "SUCCEEDED" ||
      !regenerationAcknowledged ||
      submitLockRef.current
    ) {
      return;
    }
    submitLockRef.current = true;
    setMessage("");
    const storageKey = `socialpilot.copyRegeneration.${task.id}.${strategy.id}`;
    try {
      const currentPreflight = await getCopyPreflight(task.id, strategy.id);
      if (
        !currentPreflight.ready_for_execution ||
        currentPreflight.product_id !== product.id ||
        currentPreflight.task_id !== task.id ||
        currentPreflight.strategy_id !== strategy.id
      ) {
        throw new Error("当前商品、营销任务或策略已变化，请重新检查后再生成。");
      }
      const regenerationKey =
        window.sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
      window.sessionStorage.setItem(storageKey, regenerationKey);
      const created = await enqueueCopyJob(task.id, strategy.id, {
        product_id: product.id,
        strategy_id: strategy.id,
        input_digest: currentPreflight.input_digest,
        preflight_digest: currentPreflight.preflight_digest,
        preflight_expires_at: currentPreflight.expires_at,
        cost_confirmed: true,
        regeneration_key: regenerationKey,
      });
      window.sessionStorage.removeItem(storageKey);
      setPreflight(currentPreflight);
      setJob(created.job);
      setMatrix(null);
      setReused(created.reused);
      setRegenerationRequested(false);
      setRegenerationAcknowledged(false);
      setMessage(
        created.reused
          ? "已恢复同一次重新生成任务，不会重复调用千问。"
          : "新的文案生成任务已创建，原文案矩阵仍完整保留。",
      );
    } catch (error) {
      setMessage(
        getApiErrorMessage(
          error,
          "重新生成任务创建失败；已保留请求身份，重试不会重复创建任务。",
        ),
      );
    } finally {
      submitLockRef.current = false;
    }
  }

  return (
    <section className="copy-preflight" aria-label="Copy Queue Operation">
      <div className="copy-preflight__heading">
        <div>
          <p className="eyebrow">文案矩阵任务 · 安全入队</p>
          <h5>千问社媒文案矩阵生成任务</h5>
        </div>
        <span className={`strategy-preflight__status strategy-preflight__status--${loadState}`}>
          {loadState === "loading" ? "读取中" : loadState === "ready" ? "可入队" : loadState === "blocked" ? "未就绪" : "读取失败"}
        </span>
      </div>

      <p className="copy-preflight__intro">
        网页只验证精确商品、营销任务、营销策略与冻结输入；只有后台任务领取后才调用千问。
      </p>
      <dl className="product-detail__facts copy-preflight__context">
        <div><dt>商品</dt><dd>#{product.id} · {product.name}</dd></div>
        <div><dt>营销任务</dt><dd>#{task.id}</dd></div>
        <div><dt>营销策略</dt><dd>#{strategy.id}</dd></div>
        <div><dt>策略来源</dt><dd>{strategySource === "direct" ? "任务精确结果" : "兼容来源"}</dd></div>
        <div><dt>任务平台</dt><dd>{task.platforms.join("、")}</dd></div>
      </dl>

      {preflight ? (
        <div className="copy-preflight__result">
          <dl className="product-detail__facts">
            <div><dt>冻结内容指纹</dt><dd>{preflight.input_digest.slice(0, 12)}…</dd></div>
            <div><dt>前置检查有效期</dt><dd>{new Date(preflight.expires_at).toLocaleString()}</dd></div>
            <div><dt>模型服务配置</dt><dd>{preflight.provider_configured ? "已配置" : "未配置"}</dd></div>
            <div><dt>执行契约</dt><dd>{preflight.contract_ready ? "已实现" : "尚未实现"}</dd></div>
            <div><dt>预算估算</dt><dd>{preflight.estimated_cost} {preflight.currency}</dd></div>
            <div><dt>自动重试</dt><dd>禁止（只允许一次模型提交）</dd></div>
          </dl>
          {preflight.missing_requirements.length > 0 ? (
            <div className="strategy-preflight__missing">
              <strong>仍缺少：</strong>
              <ul>{preflight.missing_requirements.map((item) => <li key={item}>{REQUIREMENT_LABELS[item] ?? item}</li>)}</ul>
            </div>
          ) : null}
          <p className="copy-preflight__boundary">
            生成结果将与当前营销策略精确关联；当前营销任务关系会作为结果证据返回。
          </p>
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
                我确认任务被后台领取后将调用一次千问，预算估算为
                {preflight.estimated_cost} {preflight.currency}，并可能产生费用。
              </label>
              <button type="button" className="button" onClick={() => void enqueue()} disabled={!canEnqueue}>
                创建文案生成任务
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

      {matrix ? (
        <CopyMatrixResult
          matrix={matrix}
          product={product}
          taskId={task.id}
          onRegenerate={() => {
            setRegenerationRequested(true);
            setRegenerationAcknowledged(false);
          }}
        />
      ) : null}
      {matrix && regenerationRequested ? (
        <div className="strategy-operation-issue copy-regeneration-confirmation">
          <strong>重新生成会再次调用一次千问</strong>
          <p>
            将沿用当前商品、营销任务和营销策略生成一套新文案；文案矩阵 #{matrix.id}
            会保留，不会被覆盖。
          </p>
          <label className="strategy-preflight__acknowledgement">
            <input
              type="checkbox"
              checked={regenerationAcknowledged}
              onChange={(event) =>
                setRegenerationAcknowledged(event.target.checked)
              }
            />
            我确认重新生成将调用一次千问，并可能产生
            {preflight?.estimated_cost ?? "未知"} {preflight?.currency ?? "CNY"}
            费用。
          </label>
          <div className="copy-result-actions">
            <button
              type="button"
              className="button"
              disabled={!regenerationAcknowledged}
              onClick={() => void regenerate()}
            >
              确认重新生成
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => {
                setRegenerationRequested(false);
                setRegenerationAcknowledged(false);
              }}
            >
              取消
            </button>
          </div>
        </div>
      ) : null}
      <p className="strategy-preflight__note">
        文案生成不代表自动发布；结果由执行任务的精确结果编号恢复，不使用模糊记录。
      </p>
    </section>
  );
}

function CopyMatrixResult({
  matrix,
  product,
  taskId,
  onRegenerate,
}: {
  matrix: PersistedCopyMatrix;
  product: Product;
  taskId: number;
  onRegenerate: () => void;
}) {
  const [copyFeedback, setCopyFeedback] = useState("");

  async function copyText(content: string, label: string) {
    try {
      await navigator.clipboard.writeText(content);
      setCopyFeedback(`${label}已复制。`);
    } catch {
      setCopyFeedback("浏览器未允许复制，请检查剪贴板权限。");
    }
  }

  function download(filename: string, content: string, contentType: string) {
    const url = URL.createObjectURL(new Blob([content], { type: contentType }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <article className="copy-operation-result" aria-live="polite">
      <header>
        <div><p className="eyebrow">队列精确结果</p><h6>平台文案结果</h6></div>
        <span>文案矩阵 #{matrix.id}</span>
      </header>
      <dl className="product-detail__facts">
        <div><dt>商品</dt><dd>#{matrix.product_id} · {product.name}</dd></div>
        <div><dt>营销任务</dt><dd>#{taskId}</dd></div>
        <div><dt>营销策略</dt><dd>#{matrix.marketing_strategy_id}</dd></div>
        <div><dt>生成平台</dt><dd>{matrix.copies.map((copy) => copy.platform).join("、")}</dd></div>
      </dl>
      <div className="copy-result-actions" aria-label="文案复制与导出">
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void copyText(copyMatrixText(matrix), "整套文案")}
        >
          复制整套文案
        </button>
        <button
          type="button"
          className="button button--secondary"
          onClick={() =>
            download(
              `copy-matrix-${matrix.id}.json`,
              JSON.stringify(matrix, null, 2),
              "application/json;charset=utf-8",
            )
          }
        >
          导出 JSON
        </button>
        <button
          type="button"
          className="button button--secondary"
          onClick={() =>
            download(
              `copy-matrix-${matrix.id}.csv`,
              copyMatrixCsv(matrix),
              "text/csv;charset=utf-8",
            )
          }
        >
          导出 CSV
        </button>
        <button type="button" className="button" onClick={onRegenerate}>
          重新生成文案
        </button>
      </div>
      {copyFeedback ? <p role="status">{copyFeedback}</p> : null}
      <div className="copy-operation-result__platforms">
        {matrix.copies.map((copy) => (
          <section key={copy.platform}>
            <header className="copy-platform-result__header">
              <h6>{copy.platform}</h6>
              <button
                type="button"
                className="button button--secondary"
                onClick={() =>
                  void copyText(platformCopyText(copy), `${copy.platform} 文案`)
                }
              >
                复制此平台
              </button>
            </header>
            <dl>
              <div><dt>开场钩子</dt><dd>{copy.hook}</dd></div>
              <div><dt>正文</dt><dd>{copy.caption}</dd></div>
              <div><dt>话题标签</dt><dd>{copy.hashtags.join(" ")}</dd></div>
              <div><dt>行动号召</dt><dd>{copy.cta}</dd></div>
            </dl>
          </section>
        ))}
      </div>
    </article>
  );
}
