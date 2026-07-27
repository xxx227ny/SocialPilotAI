import { useEffect, useRef, useState } from "react";

import {
  getLatestVideoProjectForProduct,
  getVideoRenderPreflight,
  isVideoProjectNotFound,
} from "../../api/videos";
import { videoRenderExecutionEnabled } from "../../config/features";
import type { Product } from "../../types/product";
import type {
  VideoProject,
  VideoRenderPreflight,
} from "../../types/video";

type PanelState =
  | "idle"
  | "loading_project"
  | "project_empty"
  | "project_failed"
  | "checking"
  | "ready"
  | "blocked"
  | "failed"
  | "retry";

interface ActiveContext {
  requestId: number;
  productId: number;
  videoProjectId: number | null;
}

export function VideoRenderPreflightPanel({ product }: { product: Product }) {
  const [state, setState] = useState<PanelState>("idle");
  const [project, setProject] = useState<VideoProject | null>(null);
  const [preflight, setPreflight] = useState<VideoRenderPreflight | null>(null);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const requestIdRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const retryLockRef = useRef(false);
  const activeContextRef = useRef<ActiveContext>({
    requestId: 0,
    productId: product.id,
    videoProjectId: null,
  });

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    retryLockRef.current = false;
    activeContextRef.current = {
      requestId,
      productId: product.id,
      videoProjectId: null,
    };
    setProject(null);
    setPreflight(null);
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
        if (!isActive(requestId, product.id, null, controller)) return;
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
        !isActive(requestId, product.id, null, controller)
      ) {
        return;
      }
      activeContextRef.current = {
        requestId,
        productId: product.id,
        videoProjectId: loadedProject.id,
      };
      setProject(loadedProject);
      setState("checking");

      try {
        const checked = await getVideoRenderPreflight(
          loadedProject.id,
          controller.signal,
        );
        if (
          !isActive(requestId, product.id, loadedProject.id, controller) ||
          checked.video_project_id !== loadedProject.id ||
          checked.product_id !== product.id
        ) {
          return;
        }
        setPreflight(checked);
        setState(checked.ready_for_execution ? "ready" : "blocked");
      } catch {
        if (!isActive(requestId, product.id, loadedProject.id, controller)) {
          return;
        }
        setError("Render Preflight检查失败；未创建任务，也未调用Provider。");
        setState("failed");
      }
    }

    void load();
    return () => controller.abort();
  }, [product.id, retryKey]);

  function isActive(
    requestId: number,
    productId: number,
    videoProjectId: number | null,
    controller: AbortController,
  ) {
    const active = activeContextRef.current;
    return (
      !controller.signal.aborted &&
      active.requestId === requestId &&
      active.productId === productId &&
      active.videoProjectId === videoProjectId
    );
  }

  function retry() {
    if (retryLockRef.current) return;
    retryLockRef.current = true;
    controllerRef.current?.abort();
    setState("retry");
    setRetryKey((current) => current + 1);
  }

  const loading =
    state === "loading_project" || state === "checking" || state === "retry";

  return (
    <section className="video-render-preflight" aria-busy={loading}>
      <header className="video-render-preflight__header">
        <div>
          <span>V2-C3.1A · PREFLIGHT ONLY</span>
          <h4>VideoProject → RenderTask 操作入口</h4>
          <p>只读取精确项目与安全布尔状态，不创建RenderTask或Artifact。</p>
        </div>
        <StatusBadge state={state} />
      </header>

      {state === "loading_project" || state === "retry" ? (
        <PanelMessage
          title="正在读取商品最新VideoProject"
          detail={`Product #${product.id} · 请求仅访问只读API`}
        />
      ) : state === "project_empty" ? (
        <PanelMessage
          title="尚无VideoProject"
          detail="该商品没有可进入Render Preflight的VideoProject。"
          actionLabel="重新读取"
          onAction={retry}
        />
      ) : state === "project_failed" ? (
        <PanelMessage
          title="VideoProject读取失败"
          detail={error}
          actionLabel="安全重试"
          onAction={retry}
          error
        />
      ) : project ? (
        <>
          <div className="video-render-preflight__identity">
            <Info label="Product" value={`#${product.id} · ${product.name}`} />
            <Info label="VideoProject" value={`#${project.id}`} />
            <Info label="标题" value={project.title} />
            <Info label="平台" value={project.platform} />
            <Info label="时长" value={`${project.duration_seconds} 秒`} />
            <Info label="画幅" value={project.aspect_ratio} />
            <Info label="场景" value={`${project.scenes.length} 个`} />
            <Info label="项目状态" value={project.status} />
          </div>

          <div className="video-render-preflight__concept">
            <strong>项目概念</strong>
            <p>{project.concept}</p>
          </div>

          {state === "checking" ? (
            <PanelMessage
              title="正在运行Render Preflight"
              detail="检查输入、真实关联和默认关闭状态；不会解析或调用Provider。"
            />
          ) : state === "failed" ? (
            <PanelMessage
              title="Render Preflight失败"
              detail={error}
              actionLabel="安全重试"
              onAction={retry}
              error
            />
          ) : preflight ? (
            <PreflightResult preflight={preflight} onRetry={retry} />
          ) : null}
        </>
      ) : null}

      <div className="video-render-preflight__future-action">
        <div>
          <strong>未来执行入口保持锁定</strong>
          <p>
            Frontend执行开关：
            {videoRenderExecutionEnabled ? "已配置，但本阶段仍禁止执行" : "默认关闭"}
          </p>
        </div>
        <button type="button" disabled>
          创建RenderTask · V2-C3.1B经授权后开放
        </button>
      </div>
    </section>
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
          <strong>尚缺安全契约或运行条件</strong>
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
        重新运行只读Preflight
      </button>
    </div>
  );
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
    checking: "检查中",
    ready: "输入就绪",
    blocked: "执行锁定",
    failed: "检查失败",
    retry: "准备重试",
  };
  return <span className={`video-render-preflight__status is-${state}`}>{labels[state]}</span>;
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
