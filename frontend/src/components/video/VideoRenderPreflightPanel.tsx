import { useEffect, useRef, useState } from "react";

import {
  executeVideoProjectRender,
  getLatestVideoProjectForProduct,
  getLatestVideoRenderTask,
  getVideoRenderArtifactContentUrl,
  getVideoRenderPreflight,
  isVideoProjectNotFound,
  isVideoRenderTaskNotFound,
  refreshWorkspaceVideoRenderTask,
} from "../../api/videos";
import { videoRenderExecutionEnabled } from "../../config/features";
import type { Product } from "../../types/product";
import type {
  VideoProject,
  VideoRenderOperation,
  VideoRenderPreflight,
  VideoRenderTaskStatus,
} from "../../types/video";

type PanelState =
  | "idle"
  | "loading_project"
  | "project_empty"
  | "project_failed"
  | "checking"
  | "ready"
  | "blocked"
  | "creating_task"
  | "submitting"
  | "submitted"
  | "processing"
  | "refreshing"
  | "succeeded"
  | "failed"
  | "submit_unknown"
  | "artifact_persist_failed"
  | "recovering"
  | "recovered"
  | "retry";

interface ActiveContext {
  requestId: number;
  productId: number;
  videoProjectId: number | null;
  renderTaskId: number | null;
}

const REFRESHABLE_STATUSES: VideoRenderTaskStatus[] = [
  "SUBMITTED",
  "PENDING",
  "RUNNING",
];

export function VideoRenderPreflightPanel({ product }: { product: Product }) {
  const [state, setState] = useState<PanelState>("idle");
  const [project, setProject] = useState<VideoProject | null>(null);
  const [preflight, setPreflight] = useState<VideoRenderPreflight | null>(null);
  const [operation, setOperation] = useState<VideoRenderOperation | null>(null);
  const [error, setError] = useState("");
  const [costConfirmed, setCostConfirmed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const requestIdRef = useRef(0);
  const loadControllerRef = useRef<AbortController | null>(null);
  const actionControllerRef = useRef<AbortController | null>(null);
  const retryLockRef = useRef(false);
  const submitLockRef = useRef(false);
  const refreshLockRef = useRef(false);
  const activeContextRef = useRef<ActiveContext>({
    requestId: 0,
    productId: product.id,
    videoProjectId: null,
    renderTaskId: null,
  });

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    loadControllerRef.current?.abort();
    actionControllerRef.current?.abort();
    loadControllerRef.current = controller;
    retryLockRef.current = false;
    submitLockRef.current = false;
    refreshLockRef.current = false;
    activeContextRef.current = {
      requestId,
      productId: product.id,
      videoProjectId: null,
      renderTaskId: null,
    };
    setProject(null);
    setPreflight(null);
    setOperation(null);
    setCostConfirmed(false);
    setError("");
    setState("loading_project");

    async function load() {
      let loadedProject: VideoProject;
      try {
        loadedProject = await getLatestVideoProjectForProduct(
          product.id,
          controller.signal,
        );
      } catch (loadError) {
        if (!isActive(requestId, product.id, null, null, controller)) return;
        if (isVideoProjectNotFound(loadError)) {
          setState("project_empty");
          return;
        }
        setError("VideoProject读取失败，请确认Backend可用后安全重试。");
        setState("project_failed");
        return;
      }

      if (
        loadedProject.product_id !== product.id ||
        !isActive(requestId, product.id, null, null, controller)
      ) {
        return;
      }
      activeContextRef.current = {
        requestId,
        productId: product.id,
        videoProjectId: loadedProject.id,
        renderTaskId: null,
      };
      setProject(loadedProject);
      setState("checking");

      let checked: VideoRenderPreflight;
      try {
        checked = await getVideoRenderPreflight(
          loadedProject.id,
          controller.signal,
        );
      } catch {
        if (
          !isActive(
            requestId,
            product.id,
            loadedProject.id,
            null,
            controller,
          )
        ) {
          return;
        }
        setError("Render Preflight检查失败；没有执行或调用Provider。");
        setState("failed");
        return;
      }
      if (
        checked.video_project_id !== loadedProject.id ||
        checked.product_id !== product.id ||
        !isActive(
          requestId,
          product.id,
          loadedProject.id,
          null,
          controller,
        )
      ) {
        return;
      }
      setPreflight(checked);
      setState("recovering");

      try {
        const recovered = await getLatestVideoRenderTask(
          loadedProject.id,
          controller.signal,
        );
        if (
          !operationMatches(
            recovered,
            product.id,
            loadedProject.id,
            null,
          ) ||
          !isActive(
            requestId,
            product.id,
            loadedProject.id,
            null,
            controller,
          )
        ) {
          return;
        }
        activeContextRef.current = {
          requestId,
          productId: product.id,
          videoProjectId: loadedProject.id,
          renderTaskId: recovered.task.id,
        };
        setOperation(recovered);
        setState(stateForTask(recovered.task.status, true));
      } catch (recoverError) {
        if (
          !isActive(
            requestId,
            product.id,
            loadedProject.id,
            null,
            controller,
          )
        ) {
          return;
        }
        if (isVideoRenderTaskNotFound(recoverError)) {
          setState(checked.ready_for_execution ? "ready" : "blocked");
          return;
        }
        setError("RenderTask恢复失败；未自动重新提交，请安全重试读取。");
        setState("failed");
      }
    }

    void load();
    return () => {
      controller.abort();
      actionControllerRef.current?.abort();
    };
  }, [product.id, retryKey]);

  function isActive(
    requestId: number,
    productId: number,
    videoProjectId: number | null,
    renderTaskId: number | null,
    controller: AbortController,
  ) {
    const active = activeContextRef.current;
    return (
      !controller.signal.aborted &&
      active.requestId === requestId &&
      active.productId === productId &&
      active.videoProjectId === videoProjectId &&
      (renderTaskId === null || active.renderTaskId === renderTaskId)
    );
  }

  function retryRead() {
    if (retryLockRef.current) return;
    retryLockRef.current = true;
    loadControllerRef.current?.abort();
    actionControllerRef.current?.abort();
    setState("retry");
    setRetryKey((current) => current + 1);
  }

  const executeAllowed =
    project !== null &&
    preflight !== null &&
    operation === null &&
    preflight.input_ready &&
    preflight.provider_configured &&
    preflight.execution_enabled &&
    preflight.artifact_storage_configured &&
    preflight.contract_ready &&
    preflight.ready_for_execution &&
    videoRenderExecutionEnabled &&
    costConfirmed &&
    activeContextRef.current.productId === product.id &&
    activeContextRef.current.videoProjectId === project.id &&
    !submitLockRef.current &&
    !isBusyState(state);

  async function execute() {
    if (!executeAllowed || submitLockRef.current || !project || !preflight) {
      setError("执行条件未全部满足；没有创建或提交RenderTask。");
      return;
    }
    const context = activeContextRef.current;
    if (
      context.productId !== product.id ||
      context.videoProjectId !== project.id ||
      context.renderTaskId !== null
    ) {
      setError("Product或VideoProject上下文已变化，请重新检查。");
      return;
    }
    submitLockRef.current = true;
    const controller = new AbortController();
    actionControllerRef.current?.abort();
    actionControllerRef.current = controller;
    setError("");
    setState("creating_task");
    await Promise.resolve();
    if (controller.signal.aborted) {
      submitLockRef.current = false;
      return;
    }
    setState("submitting");

    try {
      const result = await executeVideoProjectRender(
        project.id,
        controller.signal,
      );
      if (
        !operationMatches(result, product.id, project.id, null) ||
        !isActive(
          context.requestId,
          product.id,
          project.id,
          null,
          controller,
        )
      ) {
        return;
      }
      acceptOperation(result, context.requestId);
    } catch {
      if (
        controller.signal.aborted ||
        !isActive(
          context.requestId,
          product.id,
          project.id,
          null,
          controller,
        )
      ) {
        return;
      }
      setState("recovering");
      await recoverAfterUncertainAction(
        context.requestId,
        project.id,
        null,
        controller,
        "执行响应不确定；已仅执行GET恢复，没有自动重新提交。",
      );
    } finally {
      submitLockRef.current = false;
    }
  }

  const refreshAllowed =
    project !== null &&
    operation !== null &&
    REFRESHABLE_STATUSES.includes(operation.task.status) &&
    preflight?.execution_enabled === true &&
    preflight.artifact_storage_configured &&
    videoRenderExecutionEnabled &&
    activeContextRef.current.productId === product.id &&
    activeContextRef.current.videoProjectId === project.id &&
    activeContextRef.current.renderTaskId === operation.task.id &&
    !refreshLockRef.current &&
    !isBusyState(state);

  async function refresh() {
    if (
      !refreshAllowed ||
      refreshLockRef.current ||
      !project ||
      !operation
    ) {
      return;
    }
    const taskId = operation.task.id;
    const context = activeContextRef.current;
    refreshLockRef.current = true;
    const controller = new AbortController();
    actionControllerRef.current?.abort();
    actionControllerRef.current = controller;
    setError("");
    setState("refreshing");

    try {
      const result = await refreshWorkspaceVideoRenderTask(
        taskId,
        controller.signal,
      );
      if (
        !operationMatches(result, product.id, project.id, taskId) ||
        !isActive(
          context.requestId,
          product.id,
          project.id,
          taskId,
          controller,
        )
      ) {
        return;
      }
      acceptOperation(result, context.requestId);
    } catch {
      if (
        controller.signal.aborted ||
        !isActive(
          context.requestId,
          product.id,
          project.id,
          taskId,
          controller,
        )
      ) {
        return;
      }
      setState("recovering");
      await recoverAfterUncertainAction(
        context.requestId,
        project.id,
        taskId,
        controller,
        "刷新响应不确定；已仅执行GET恢复，没有submit或自动轮询。",
      );
    } finally {
      refreshLockRef.current = false;
    }
  }

  async function recoverAfterUncertainAction(
    requestId: number,
    videoProjectId: number,
    expectedTaskId: number | null,
    controller: AbortController,
    fallback: string,
  ) {
    try {
      const recovered = await getLatestVideoRenderTask(
        videoProjectId,
        controller.signal,
      );
      if (
        !operationMatches(
          recovered,
          product.id,
          videoProjectId,
          expectedTaskId,
        ) ||
        !isActive(
          requestId,
          product.id,
          videoProjectId,
          expectedTaskId,
          controller,
        )
      ) {
        return;
      }
      acceptOperation(recovered, requestId);
    } catch {
      if (!controller.signal.aborted) {
        setError(fallback);
        setState("failed");
      }
    }
  }

  function acceptOperation(result: VideoRenderOperation, requestId: number) {
    activeContextRef.current = {
      requestId,
      productId: result.product_id,
      videoProjectId: result.video_project_id,
      renderTaskId: result.task.id,
    };
    setOperation(result);
    setState(stateForTask(result.task.status, result.recovered));
  }

  const loading =
    state === "loading_project" ||
    state === "checking" ||
    state === "recovering" ||
    state === "retry";

  return (
    <section className="video-render-preflight" aria-busy={loading}>
      <header className="video-render-preflight__header">
        <div>
          <span>V2-C3.1B · EXACT PROJECT CONTRACT</span>
          <h4>VideoProject → RenderTask → Artifact</h4>
          <p>
            精确项目、单Scene任务、显式刷新和服务器稳定Artifact；没有自动轮询。
          </p>
        </div>
        <StatusBadge state={state} />
      </header>

      {state === "loading_project" || state === "retry" ? (
        <PanelMessage
          title="正在读取商品最新VideoProject"
          detail={`Product #${product.id} · 只读恢复，不自动执行`}
        />
      ) : state === "project_empty" ? (
        <PanelMessage
          title="尚无VideoProject"
          detail="该商品没有可执行或恢复的VideoProject。"
          actionLabel="重新读取"
          onAction={retryRead}
        />
      ) : state === "project_failed" ? (
        <PanelMessage
          title="VideoProject读取失败"
          detail={error}
          actionLabel="安全重试"
          onAction={retryRead}
          error
        />
      ) : project ? (
        <>
          <ProjectIdentity product={product} project={project} />
          {state === "checking" || state === "recovering" ? (
            <PanelMessage
              title={
                state === "checking"
                  ? "正在运行Render Preflight"
                  : "正在恢复该项目最新RenderTask"
              }
              detail="GET操作不会调用Provider、submit、refresh或创建Artifact。"
            />
          ) : preflight ? (
            <PreflightResult preflight={preflight} onRetry={retryRead} />
          ) : null}

          {operation ? (
            <TaskResult
              operation={operation}
              refreshAllowed={refreshAllowed}
              onRefresh={refresh}
            />
          ) : null}
        </>
      ) : null}

      {error && state !== "project_failed" ? (
        <p className="video-render-preflight__safe-error">{error}</p>
      ) : null}

      <div className="video-render-preflight__execution">
        <label>
          <input
            type="checkbox"
            checked={costConfirmed}
            disabled={operation !== null || isBusyState(state)}
            onChange={(event) => setCostConfirmed(event.target.checked)}
          />
          <span>
            我理解真实视频生成会调用阿里云百炼Wanx，并可能消耗比赛Credits。
          </span>
        </label>
        <div>
          <p>
            Frontend开关：
            {videoRenderExecutionEnabled ? "已启用" : "默认关闭"}
          </p>
          <button
            type="button"
            disabled={!executeAllowed}
            onClick={() => void execute()}
          >
            {state === "creating_task"
              ? "正在创建RenderTask…"
              : state === "submitting"
                ? "正在提交Wanx任务…"
                : operation
                  ? "该精确项目已有RenderTask"
                  : "创建并提交RenderTask"}
          </button>
        </div>
      </div>
    </section>
  );
}

function ProjectIdentity({
  product,
  project,
}: {
  product: Product;
  project: VideoProject;
}) {
  return (
    <div className="video-render-preflight__identity">
      <Info label="Product" value={`#${product.id} · ${product.name}`} />
      <Info label="VideoProject" value={`#${project.id}`} />
      <Info
        label="Strategy"
        value={`#${project.marketing_strategy_id}`}
      />
      <Info label="CopyMatrix" value={`#${project.copy_matrix_id}`} />
      <Info label="标题" value={project.title} />
      <Info label="平台" value={project.platform} />
      <Info label="时长" value={`${project.duration_seconds} 秒`} />
      <Info label="画幅" value={project.aspect_ratio} />
      <Info label="场景" value={`${project.scenes.length} 个`} />
      <Info label="项目状态" value={project.status} />
    </div>
  );
}

function PreflightResult({
  preflight,
  onRetry,
}: {
  preflight: VideoRenderPreflight;
  onRetry: () => void;
}) {
  return (
    <div className="video-render-preflight__result">
      <div className="video-render-preflight__checks">
        <Check label="输入完整" value={preflight.input_ready} />
        <Check
          label={`${preflight.provider}已配置`}
          value={preflight.provider_configured}
        />
        <Check
          label="Backend执行开关"
          value={preflight.execution_enabled}
        />
        <Check
          label="Artifact存储"
          value={preflight.artifact_storage_configured}
        />
        <Check label="执行契约完整" value={preflight.contract_ready} />
        <Check label="允许执行" value={preflight.ready_for_execution} />
      </div>
      <p className="video-render-preflight__association">
        {preflight.association_notice}
      </p>
      <p className="video-render-preflight__association">
        持久化关联：Product #{preflight.product_id} · MarketingStrategy #
        {preflight.marketing_strategy_id} · CopyMatrix #
        {preflight.copy_matrix_id}。没有MarketingBrief外键。
      </p>
      {preflight.missing_requirements.length > 0 ? (
        <div className="video-render-preflight__missing">
          <strong>尚缺运行条件</strong>
          <ul>
            {preflight.missing_requirements.map((requirement) => (
              <li key={requirement}>{requirement}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="video-render-preflight__cost">
        {preflight.estimated_cost_notice}
      </p>
      <button
        className="video-render-preflight__retry"
        type="button"
        onClick={onRetry}
      >
        重新运行只读Preflight与恢复
      </button>
    </div>
  );
}

function TaskResult({
  operation,
  refreshAllowed,
  onRefresh,
}: {
  operation: VideoRenderOperation;
  refreshAllowed: boolean;
  onRefresh: () => Promise<void>;
}) {
  const { task, artifact } = operation;
  return (
    <div className="video-render-task-result">
      <header>
        <div>
          <span>
            {operation.recovered ? "重载恢复记录" : "本次执行或复用结果"}
          </span>
          <h5>RenderTask #{task.id}</h5>
        </div>
        <strong>{task.status}</strong>
      </header>
      <div className="video-render-task-result__facts">
        <Info label="Provider" value={task.provider_name ?? "尚未确认"} />
        <Info label="Provider状态" value={task.status} />
        <Info label="Scene" value={`#${task.scene_sequence}`} />
        <Info label="时长" value={`${task.duration_seconds} 秒`} />
        <Info label="画幅" value={task.aspect_ratio} />
        <Info label="分辨率" value={task.resolution} />
        <Info label="创建时间" value={formatDateTime(task.created_at)} />
        <Info label="更新时间" value={formatDateTime(task.updated_at)} />
      </div>
      <p className="video-render-preflight__association">
        {operation.association_notice}
      </p>
      {task.error_code ? (
        <div className="video-render-task-result__error">
          <strong>{safeErrorLabel(task.error_code)}</strong>
          <p>{task.error_message ?? "任务未完成；未显示Provider原始响应。"}</p>
        </div>
      ) : null}
      {task.status === "SUBMIT_UNKNOWN" ? (
        <p className="video-render-task-result__warning">
          Provider可能已接收请求，但本地没有可靠确认。当前Provider不支持按客户端幂等键自动核对，因此禁止自动重新submit。
        </p>
      ) : null}
      {artifact ? (
        <div className="video-render-artifact">
          <div>
            <strong>稳定Artifact #{artifact.id}</strong>
            <span>
              {artifact.content_type} · {formatBytes(artifact.size_bytes)}
            </span>
          </div>
          <video
            controls
            preload="metadata"
            src={getVideoRenderArtifactContentUrl(artifact.id)}
          >
            当前浏览器不支持视频播放。
          </video>
        </div>
      ) : (
        <p className="video-render-task-result__artifact-empty">
          Artifact：尚未持久化
        </p>
      )}
      <button
        className="video-render-task-result__refresh"
        type="button"
        disabled={!refreshAllowed}
        onClick={() => void onRefresh()}
      >
        显式刷新Provider状态
      </button>
    </div>
  );
}

function operationMatches(
  operation: VideoRenderOperation,
  productId: number,
  videoProjectId: number,
  renderTaskId: number | null,
) {
  return (
    operation.product_id === productId &&
    operation.video_project_id === videoProjectId &&
    operation.task.video_project_id === videoProjectId &&
    (renderTaskId === null || operation.task.id === renderTaskId)
  );
}

function stateForTask(
  status: VideoRenderTaskStatus,
  recovered: boolean,
): PanelState {
  if (status === "SUBMIT_UNKNOWN") return "submit_unknown";
  if (status === "ARTIFACT_PERSIST_FAILED") {
    return "artifact_persist_failed";
  }
  if (status === "FAILED" || status === "CANCELED") return "failed";
  if (status === "SUCCEEDED") return "succeeded";
  if (recovered) return "recovered";
  if (status === "SUBMITTED" || status === "PENDING") return "submitted";
  if (status === "RUNNING" || status === "REFRESHING") return "processing";
  if (status === "SUBMITTING") return "submitting";
  return "creating_task";
}

function isBusyState(state: PanelState) {
  return [
    "loading_project",
    "checking",
    "creating_task",
    "submitting",
    "refreshing",
    "recovering",
    "retry",
  ].includes(state);
}

function safeErrorLabel(code: string) {
  const labels: Record<string, string> = {
    execution_disabled: "执行已关闭",
    provider_not_configured: "Provider未配置",
    artifact_storage_not_configured: "Artifact存储未配置",
    association_mismatch: "关联不一致",
    invalid_input: "输入无效",
    authentication: "认证失败",
    quota_or_rate_limit: "配额或限流",
    network: "网络错误",
    timeout: "请求超时",
    invalid_provider_output: "Provider输出无效",
    submit_unknown_network: "Submit状态不确定",
    submit_unknown_timeout: "Submit状态不确定",
    artifact_persist_failed: "Artifact持久化失败",
    backend: "Backend错误",
    not_found: "记录不存在",
    unknown: "未知错误",
    provider_failed: "Provider任务失败",
  };
  return labels[code] ?? "安全错误";
}

function Check({ label, value }: { label: string; value: boolean }) {
  return (
    <span className={value ? "is-ready" : "is-blocked"}>
      {value ? "✓" : "×"} {label}
    </span>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusBadge({ state }: { state: PanelState }) {
  const labels: Record<PanelState, string> = {
    idle: "待检查",
    loading_project: "读取项目",
    project_empty: "暂无项目",
    project_failed: "读取失败",
    checking: "Preflight",
    ready: "可以执行",
    blocked: "执行锁定",
    creating_task: "创建任务",
    submitting: "提交中",
    submitted: "已提交",
    processing: "处理中",
    refreshing: "刷新中",
    succeeded: "已完成",
    failed: "失败",
    submit_unknown: "提交不确定",
    artifact_persist_failed: "存储失败",
    recovering: "恢复中",
    recovered: "已恢复",
    retry: "准备重试",
  };
  return (
    <span className={`video-render-preflight__status is-${state}`}>
      {labels[state]}
    </span>
  );
}

function PanelMessage({
  title,
  detail,
  actionLabel,
  onAction,
  error = false,
}: {
  title: string;
  detail: string;
  actionLabel?: string;
  onAction?: () => void;
  error?: boolean;
}) {
  return (
    <div className={`video-render-preflight__message${error ? " is-error" : ""}`}>
      <strong>{title}</strong>
      <p>{detail}</p>
      {actionLabel && onAction ? (
        <button type="button" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}
