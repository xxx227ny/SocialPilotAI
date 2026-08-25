import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  enqueueInitialVideoProject,
  getInitialVideoProjectJob,
  getInitialVideoProjectSource,
  getVideoProject,
  isCurrentInitialVideoOperation,
  listInitialVideoProjectJobs,
  preflightInitialVideoProject,
  retryInitialVideoProjectJob,
} from "../../api/videos";
import type { InitialVideoOperationIdentity } from "../../api/videos";
import { videoProjectExecutionEnabled } from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { ExecutionJob } from "../../types/execution";
import type { Product } from "../../types/product";
import type {
  InitialVideoProjectPreflight,
  InitialVideoProjectSource,
  InitialVideoProjectSourceRequest,
  VideoProject,
} from "../../types/video";
import {
  canEnqueueInitialVideoProject,
  exactInitialVideoProjectResultId,
  initialVideoProjectJobAllowsExplicitRetry,
  initialVideoProjectJobNeedsPolling,
  selectExactInitialVideoProjectJob,
  selectExactInitialVideoSource,
} from "./initialVideoProjectState";

type SourceState = "loading" | "ready" | "missing" | "error";
type OperationState = "idle" | "loading" | "ready" | "blocked" | "error";
type InitialPlatform = InitialVideoProjectSourceRequest["platform"];

const MISSING_LABELS: Record<string, string> = {
  product_input: "商品资料不完整",
  strategy_schema: "营销策略结构不完整",
  copy_matrix_schema: "文案矩阵结构不完整",
  source_association: "商品、策略与文案矩阵不匹配",
  platform_copy: "缺少所选平台的文案",
  provider_configuration: "千问服务配置不可用",
  qwen_credentials_configuration: "千问凭据配置不可用",
  video_project_execution: "后端视频蓝图执行功能未开启",
};

export function InitialVideoProjectPanel({
  product,
  onGenerated,
}: {
  product: Product;
  onGenerated: (videoProjectId: number) => void;
}) {
  const { isPresentation } = usePresentationMode();
  const [sourceState, setSourceState] = useState<SourceState>("loading");
  const [sourceError, setSourceError] = useState("");
  const [source, setSource] = useState<InitialVideoProjectSource | null>(null);
  const [platform, setPlatform] = useState<InitialPlatform>("TikTok");
  const [duration, setDuration] = useState<15 | 30>(30);
  const [preflight, setPreflight] =
    useState<InitialVideoProjectPreflight | null>(null);
  const [operationState, setOperationState] =
    useState<OperationState>("idle");
  const [message, setMessage] = useState("");
  const [costConfirmed, setCostConfirmed] = useState(false);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [jobReused, setJobReused] = useState(false);
  const [result, setResult] = useState<VideoProject | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const operationIdRef = useRef(0);
  const submitLockRef = useRef<InitialVideoOperationIdentity | null>(null);
  const retryLockRef = useRef<InitialVideoOperationIdentity | null>(null);
  const contextRef = useRef({ productId: product.id, operationId: 0 });
  contextRef.current.productId = product.id;

  const exactSource = useMemo(
    () => (source ? selectExactInitialVideoSource(product.id, source) : null),
    [product.id, source],
  );
  const request = useMemo<InitialVideoProjectSourceRequest | null>(
    () =>
      exactSource
        ? {
            ...exactSource,
            platform,
            duration_seconds: duration,
            aspect_ratio: "9:16",
          }
        : null,
    [duration, exactSource, platform],
  );
  const canEnqueue = canEnqueueInitialVideoProject({
    frontendGateEnabled: videoProjectExecutionEnabled,
    preflight,
    request,
    costConfirmed,
    submitLocked: submitLockRef.current !== null,
    job,
  });

  function beginOperation(): { controller: AbortController; id: number } {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const id = ++operationIdRef.current;
    contextRef.current = { productId: product.id, operationId: id };
    return { controller, id };
  }

  function isCurrent(
    id: number,
    productId: number,
    controller: AbortController,
  ): boolean {
    return isCurrentInitialVideoOperation(
      { productId, operationId: id, controller },
      contextRef.current.productId,
      contextRef.current.operationId,
      controllerRef.current,
    );
  }

  function resetQueueState() {
    setPreflight(null);
    setOperationState("idle");
    setMessage("");
    setCostConfirmed(false);
    setJob(null);
    setJobReused(false);
    setResult(null);
    submitLockRef.current = null;
    retryLockRef.current = null;
  }

  async function loadPreflightAndJobs(
    exactRequest: InitialVideoProjectSourceRequest,
    controller: AbortController,
    operationId: number,
    productId: number,
  ) {
    setOperationState("loading");
    const checked = await preflightInitialVideoProject(
      productId,
      exactRequest,
      controller.signal,
    );
    if (!isCurrent(operationId, productId, controller)) return;
    setPreflight(checked);
    setOperationState(checked.ready_for_execution ? "ready" : "blocked");
    const jobs = await listInitialVideoProjectJobs(productId, controller.signal);
    if (!isCurrent(operationId, productId, controller)) return;
    const restored = selectExactInitialVideoProjectJob(
      jobs,
      productId,
      exactRequest,
      checked.input_digest,
    );
    setJob(restored);
    setJobReused(restored !== null);
  }

  async function loadSources() {
    if (isPresentation) return;
    const productId = product.id;
    const currentPlatform = platform;
    const currentDuration = duration;
    const { controller, id } = beginOperation();
    setSourceState("loading");
    setSourceError("");
    setSource(null);
    resetQueueState();
    try {
      const loaded = await getInitialVideoProjectSource(
        productId,
        controller.signal,
      );
      if (!isCurrent(id, productId, controller)) return;
      const selected = selectExactInitialVideoSource(productId, loaded);
      if (!selected) throw new Error("Initial source identity mismatch");
      setSource(loaded);
      setSourceState("ready");
      await loadPreflightAndJobs(
        {
          ...selected,
          platform: currentPlatform,
          duration_seconds: currentDuration,
          aspect_ratio: "9:16",
        },
        controller,
        id,
        productId,
      );
    } catch (error) {
      if (!isCurrent(id, productId, controller)) return;
      setSourceState("missing");
      setOperationState("error");
      setSourceError(
        getApiErrorMessage(
          error,
          "No exact Strategy and CopyMatrix source is available.",
        ),
      );
    }
  }

  useEffect(() => {
    if (!isPresentation) void loadSources();
    return () => {
      controllerRef.current?.abort();
      operationIdRef.current += 1;
    };
  }, [product.id, isPresentation]);

  useEffect(() => {
    if (isPresentation || !initialVideoProjectJobNeedsPolling(job)) return;
    const jobId = job?.id;
    if (jobId === undefined) return;
    const context = { ...contextRef.current };
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getInitialVideoProjectJob(jobId)
        .then((next) => {
          if (
            !cancelled &&
            contextRef.current.productId === context.productId &&
            contextRef.current.operationId === context.operationId
          ) {
            setJob(next);
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setMessage(
              getApiErrorMessage(
                error,
                "Local ExecutionJob polling failed; the job was not resubmitted.",
              ),
            );
          }
        });
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [isPresentation, job]);

  useEffect(() => {
    if (isPresentation || !request) return;
    const resultId = exactInitialVideoProjectResultId(job);
    if (resultId === null) {
      if (job?.status !== "SUCCEEDED") setResult(null);
      return;
    }
    const controller = new AbortController();
    const productId = product.id;
    const expected = { ...request };
    void getVideoProject(resultId, controller.signal)
      .then((project) => {
        if (
          !controller.signal.aborted &&
          contextRef.current.productId === productId &&
          project.id === resultId &&
          project.product_id === productId &&
          project.marketing_strategy_id === expected.strategy_id &&
          project.copy_matrix_id === expected.copy_matrix_id &&
          project.platform === expected.platform &&
          project.duration_seconds === expected.duration_seconds &&
          project.aspect_ratio === expected.aspect_ratio
        ) {
          setResult(project);
          onGenerated(project.id);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMessage(
            getApiErrorMessage(
              error,
              "The exact VideoProject result could not be loaded; latest was not used.",
            ),
          );
        }
      });
    return () => controller.abort();
  }, [isPresentation, job, onGenerated, product.id, request]);

  function changePlatform(value: InitialPlatform) {
    beginOperation();
    setPlatform(value);
    resetQueueState();
  }

  function changeDuration(value: 15 | 30) {
    beginOperation();
    setDuration(value);
    resetQueueState();
  }

  async function runPreflight() {
    if (!request || operationState === "loading") return;
    const productId = product.id;
    const exactRequest = { ...request };
    const { controller, id } = beginOperation();
    resetQueueState();
    try {
      await loadPreflightAndJobs(
        exactRequest,
        controller,
        id,
        productId,
      );
    } catch (error) {
      if (!isCurrent(id, productId, controller)) return;
      setOperationState("error");
      setMessage(
        getApiErrorMessage(
          error,
          "VideoProject Preflight failed; Qwen was not called.",
        ),
      );
    }
  }

  async function enqueue() {
    if (!canEnqueue || !request || !preflight || submitLockRef.current) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const identity: InitialVideoOperationIdentity = {
      productId: product.id,
      operationId: contextRef.current.operationId,
      controller,
    };
    submitLockRef.current = identity;
    setMessage("");
    try {
      const created = await enqueueInitialVideoProject(
        identity.productId,
        {
          ...request,
          product_id: identity.productId,
          input_digest: preflight.input_digest,
          preflight_digest: preflight.preflight_digest,
          preflight_expires_at: preflight.expires_at,
          cost_confirmed: true,
        },
        controller.signal,
      );
      if (!isCurrentInitialVideoOperation(
        identity,
        contextRef.current.productId,
        contextRef.current.operationId,
        controllerRef.current,
      )) return;
      setJob(created.job);
      setJobReused(created.reused);
    } catch (error) {
      if (!isCurrentInitialVideoOperation(
        identity,
        contextRef.current.productId,
        contextRef.current.operationId,
        controllerRef.current,
      )) return;
      setMessage(
        getApiErrorMessage(
          error,
          "VideoProject enqueue failed; Provider was not called by HTTP.",
        ),
      );
    } finally {
      if (
        isCurrentInitialVideoOperation(
          identity,
          contextRef.current.productId,
          contextRef.current.operationId,
          controllerRef.current,
        ) && submitLockRef.current === identity
      ) {
        submitLockRef.current = null;
      }
    }
  }

  async function retryFailedJob() {
    if (
      !initialVideoProjectJobAllowsExplicitRetry(job) ||
      !job ||
      retryLockRef.current
    ) {
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const identity: InitialVideoOperationIdentity = {
      productId: product.id,
      operationId: contextRef.current.operationId,
      controller,
    };
    retryLockRef.current = identity;
    setMessage("");
    try {
      const retried = await retryInitialVideoProjectJob(
        job.id,
        controller.signal,
      );
      if (!isCurrentInitialVideoOperation(
        identity,
        contextRef.current.productId,
        contextRef.current.operationId,
        controllerRef.current,
      )) return;
      setJob(retried);
    } catch (error) {
      if (!isCurrentInitialVideoOperation(
        identity,
        contextRef.current.productId,
        contextRef.current.operationId,
        controllerRef.current,
      )) return;
      setMessage(getApiErrorMessage(error, "Explicit retry could not be queued."));
    } finally {
      if (
        isCurrentInitialVideoOperation(
          identity,
          contextRef.current.productId,
          contextRef.current.operationId,
          controllerRef.current,
        ) && retryLockRef.current === identity
      ) {
        retryLockRef.current = null;
      }
    }
  }

  if (isPresentation) return null;

  return (
    <section className="initial-video-project" aria-label="初始视频蓝图任务">
      <header>
        <div>
          <span>初始视频蓝图</span>
          <h4>千问初始视频蓝图任务</h4>
          <p>前置检查和任务入队不会调用模型；只有后台任务确认领取后才会调用千问。</p>
        </div>
        <strong>{videoProjectExecutionEnabled ? "前端功能已开启" : "前端功能未开启"}</strong>
      </header>

      {sourceState === "loading" ? <p>正在查找可用的文案矩阵来源……</p> : null}
      {sourceState !== "loading" && (!source || !exactSource) ? (
        <div className="initial-video-project__state">
          <p>{sourceError || "营销策略或文案矩阵尚未就绪。"}</p>
          <button type="button" onClick={() => void loadSources()}>重新读取精确来源</button>
        </div>
      ) : null}

      {source && exactSource ? (
        <>
          <dl className="initial-video-project__identity">
            <div><dt>商品</dt><dd>#{source.product_id}</dd></div>
            <div><dt>营销策略</dt><dd>#{source.strategy_id}</dd></div>
            <div><dt>文案矩阵</dt><dd>#{source.copy_matrix_id}</dd></div>
            <div><dt>来源</dt><dd>当前商品可用的精确文案矩阵</dd></div>
          </dl>
          <button className="text-button" type="button" onClick={() => void loadSources()}>
            重新读取来源和精确任务历史
          </button>

          <div className="initial-video-project__controls">
            <label>目标平台
              <select value={platform} onChange={(event) => changePlatform(event.target.value as InitialPlatform)}>
                <option value="TikTok">TikTok</option>
                <option value="Instagram">Instagram</option>
                <option value="Facebook">Facebook</option>
              </select>
            </label>
            <label>视频时长
              <select value={duration} onChange={(event) => changeDuration(Number(event.target.value) as 15 | 30)}>
                <option value={15}>15 秒</option>
                <option value={30}>30 秒</option>
              </select>
            </label>
            <label>画面比例<input value="9:16" readOnly /></label>
          </div>

          <button type="button" onClick={() => void runPreflight()} disabled={operationState === "loading"}>
            {operationState === "loading" ? "检查中……" : "运行零模型调用前置检查"}
          </button>

          {preflight ? (
            <div className="initial-video-project__preflight">
              <strong>{preflight.ready_for_execution ? "可以执行" : "暂不可执行"}</strong>
              <dl>
                <div><dt>冻结输入</dt><dd>{preflight.input_digest.slice(0, 12)}…</dd></div>
                <div><dt>有效期</dt><dd>{formatTime(preflight.expires_at)}</dd></div>
                <div><dt>模型调用</dt><dd>{preflight.provider_calls}</dd></div>
                <div><dt>数据库写入</dt><dd>{preflight.database_writes}</dd></div>
              </dl>
              {preflight.missing_requirements.length > 0 ? (
                <ul>{preflight.missing_requirements.map((item) => <li key={item}>{MISSING_LABELS[item] ?? item}</li>)}</ul>
              ) : null}
              <p>{preflight.cost_notice}</p>
            </div>
          ) : null}

          {preflight?.ready_for_execution && !job ? (
            <>
              <label className="initial-video-project__confirmation">
                <input
                  type="checkbox"
                  checked={costConfirmed}
                  onChange={(event) => setCostConfirmed(event.target.checked)}
                />
                我明确确认：后台任务可能调用千问一次并产生费用。
              </label>
              <button type="button" onClick={() => void enqueue()} disabled={!canEnqueue}>
                确认费用并创建视频蓝图任务
              </button>
            </>
          ) : null}

          {message ? <p className="initial-video-project__error" role="alert">{message}</p> : null}

          {job ? (
            <article className="strategy-operation-result" aria-live="polite">
              <header>
                <div><span>{jobReused ? "已恢复/复用" : "已创建"}</span><h5>执行任务 #{job.id}</h5></div>
                <strong>{executionStatusLabel(job.status)}</strong>
              </header>
              <dl>
                <div><dt>尝试次数</dt><dd>{job.attempt_count} / {job.max_attempts}</dd></div>
                <div><dt>冻结输入</dt><dd>{job.input_digest.slice(0, 12)}…</dd></div>
                <div><dt>安全错误码</dt><dd>{job.safe_error_code ?? "无"}</dd></div>
              </dl>
              {job.status === "QUEUED" ? <p role="status">任务已排队，等待后台执行。</p> : null}
              {job.status === "RUNNING" ? <p role="status">后台正在执行；本页面只读取本地任务状态。</p> : null}
              {job.status === "FAILED" ? (
                <div role="alert">
                  <strong>任务明确失败</strong>
                  <p>系统不会自动重试。</p>
                  {initialVideoProjectJobAllowsExplicitRetry(job) ? (
                    <button type="button" onClick={() => void retryFailedJob()}>明确重试一次</button>
                  ) : null}
                </div>
              ) : null}
              {job.status === "SUBMIT_UNKNOWN" ? (
                <div role="alert">
                  <strong>模型提交状态不确定</strong>
                  <p>为避免重复扣费，禁止自动或人工重试。</p>
                </div>
              ) : null}
            </article>
          ) : null}

          {result ? (
            <article className="initial-video-project__result">
              <span>精确任务结果</span>
              <h5>视频蓝图 #{result.id}</h5>
              <p>{result.title}</p>
              <dl>
                <div><dt>营销策略</dt><dd>#{result.marketing_strategy_id}</dd></div>
                <div><dt>文案矩阵</dt><dd>#{result.copy_matrix_id}</dd></div>
                <div><dt>目标平台</dt><dd>{result.platform}</dd></div>
                <div><dt>视频时长</dt><dd>{result.duration_seconds} 秒</dd></div>
              </dl>
              <p>系统会把这个精确结果编号传给后续渲染流程。</p>
            </article>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间无效"
    : date.toLocaleString("zh-CN");
}

function executionStatusLabel(status: string) {
  return ({
    QUEUED: "排队中",
    RUNNING: "执行中",
    SUCCEEDED: "已成功",
    FAILED: "已失败",
    SUBMIT_UNKNOWN: "提交状态不确定",
  } as Record<string, string>)[status] ?? status;
}
