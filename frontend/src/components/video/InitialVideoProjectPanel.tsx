import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  executeInitialVideoProject,
  getInitialVideoProjectSource,
  preflightInitialVideoProject,
} from "../../api/videos";
import { videoProjectExecutionEnabled } from "../../config/features";
import type { PlatformCopy } from "../../types/copy";
import type { Product } from "../../types/product";
import type {
  InitialVideoProjectExecutionResult,
  InitialVideoProjectPreflight,
  InitialVideoProjectSource,
  InitialVideoProjectSourceRequest,
} from "../../types/video";
import {
  canExecuteInitialVideoProject,
  selectExactInitialVideoSource,
} from "./initialVideoProjectState";

type SourceState = "loading" | "ready" | "missing" | "error";
type OperationState = "idle" | "loading" | "failed" | "succeeded";
type InitialPlatform = PlatformCopy["platform"];

const MISSING_LABELS: Record<string, string> = {
  product_input: "Product输入不完整",
  strategy_schema: "Strategy Schema不完整",
  copy_matrix_schema: "CopyMatrix Schema不完整",
  source_association: "Product、Strategy与CopyMatrix身份不一致",
  platform_copy: "CopyMatrix缺少所选平台文案",
  provider_configuration: "Qwen配置未就绪",
  qwen_credentials_configuration: "Qwen凭据未配置",
  video_project_execution: "Backend VideoProject Gate关闭",
};

export function InitialVideoProjectPanel({
  product,
  onGenerated,
}: {
  product: Product;
  onGenerated: (videoProjectId: number) => void;
}) {
  const [sourceState, setSourceState] = useState<SourceState>("loading");
  const [sourceError, setSourceError] = useState("");
  const [source, setSource] = useState<InitialVideoProjectSource | null>(null);
  const [platform, setPlatform] = useState<InitialPlatform>("TikTok");
  const [duration, setDuration] = useState<15 | 30>(30);
  const [preflight, setPreflight] = useState<InitialVideoProjectPreflight | null>(null);
  const [preflightState, setPreflightState] = useState<OperationState>("idle");
  const [preflightError, setPreflightError] = useState("");
  const [costConfirmed, setCostConfirmed] = useState(false);
  const [executionState, setExecutionState] = useState<OperationState>("idle");
  const [executionError, setExecutionError] = useState("");
  const [result, setResult] = useState<InitialVideoProjectExecutionResult | null>(null);
  const sourceRequestId = useRef(0);
  const executionLock = useRef(false);

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
  const executeEnabled = canExecuteInitialVideoProject({
    frontendGateEnabled: videoProjectExecutionEnabled,
    preflight,
    request,
    costConfirmed,
    executionLocked: executionState === "loading",
    resultPresent: result !== null,
  });

  useEffect(() => {
    void loadSources();
    return () => {
      sourceRequestId.current += 1;
    };
  }, [product.id]);

  function invalidateOperation() {
    setPreflight(null);
    setPreflightState("idle");
    setPreflightError("");
    setCostConfirmed(false);
    setExecutionState("idle");
    setExecutionError("");
    setResult(null);
  }

  async function loadSources() {
    const requestId = ++sourceRequestId.current;
    setSourceState("loading");
    setSourceError("");
    setSource(null);
    invalidateOperation();
    try {
      const loadedSource = await getInitialVideoProjectSource(product.id);
      if (requestId !== sourceRequestId.current) return;
      if (!selectExactInitialVideoSource(product.id, loadedSource)) {
        throw new Error("读取到的Strategy与CopyMatrix身份不一致");
      }
      setSource(loadedSource);
      setSourceState("ready");
    } catch (error) {
      if (requestId !== sourceRequestId.current) return;
      setSourceState("missing");
      setSourceError(
        getApiErrorMessage(
          error,
          "尚未找到可用于第一版Video Blueprint的Strategy与CopyMatrix。",
        ),
      );
    }
  }

  function changePlatform(value: InitialPlatform) {
    setPlatform(value);
    invalidateOperation();
  }

  function changeDuration(value: 15 | 30) {
    setDuration(value);
    invalidateOperation();
  }

  async function runPreflight() {
    if (!request || preflightState === "loading") return;
    setPreflightState("loading");
    setPreflightError("");
    setPreflight(null);
    setCostConfirmed(false);
    setExecutionState("idle");
    setExecutionError("");
    setResult(null);
    try {
      const checked = await preflightInitialVideoProject(product.id, request);
      setPreflight(checked);
      setPreflightState("succeeded");
    } catch (error) {
      setPreflightState("failed");
      setPreflightError(
        getApiErrorMessage(error, "VideoProject Preflight失败；未调用Qwen。"),
      );
    }
  }

  async function execute() {
    if (!executeEnabled || !request || !preflight || executionLock.current) return;
    executionLock.current = true;
    setExecutionState("loading");
    setExecutionError("");
    try {
      const generated = await executeInitialVideoProject(product.id, {
        ...request,
        expected_preflight_digest: preflight.preflight_digest,
        preflight_expires_at: preflight.expires_at,
        confirm_cost: true,
      });
      setResult(generated);
      setExecutionState("succeeded");
      onGenerated(generated.generated_video_project.id);
    } catch (error) {
      setExecutionState("failed");
      setExecutionError(
        getApiErrorMessage(
          error,
          "VideoProject结果失败或不确定；未自动重试，也未读取latest结果。请重新执行Preflight。",
        ),
      );
      setCostConfirmed(false);
    } finally {
      executionLock.current = false;
    }
  }

  return (
    <section className="initial-video-project" aria-label="创建第一版Video Blueprint">
      <header>
        <div>
          <span>INITIAL VIDEO BLUEPRINT</span>
          <h4>创建第一版Video Blueprint</h4>
          <p>只读确认精确来源后Preflight；费用确认与Qwen执行严格分开。</p>
        </div>
        <strong>{videoProjectExecutionEnabled ? "Frontend Gate开启" : "Frontend Gate关闭"}</strong>
      </header>

      {sourceState === "loading" ? (
        <p>正在只读发现当前Strategy与CopyMatrix…</p>
      ) : sourceState !== "ready" || !source || !exactSource ? (
        <div className="initial-video-project__state">
          <p>{sourceError || "Strategy或CopyMatrix尚未就绪。"}</p>
          <button type="button" onClick={() => void loadSources()}>重新读取现有来源</button>
        </div>
      ) : (
        <>
          <dl className="initial-video-project__identity">
            <div><dt>Product</dt><dd>#{source.product_id}</dd></div>
            <div><dt>Strategy</dt><dd>#{source.strategy_id}</dd></div>
            <div><dt>CopyMatrix</dt><dd>#{source.copy_matrix_id}</dd></div>
            <div><dt>关联</dt><dd>精确匹配</dd></div>
          </dl>
          <button className="text-button" type="button" onClick={() => void loadSources()}>
            重新读取现有来源
          </button>

          <div className="initial-video-project__controls">
            <label>
              平台
              <select value={platform} onChange={(event) => changePlatform(event.target.value as InitialPlatform)}>
                <option value="TikTok">TikTok</option>
                <option value="Instagram">Instagram</option>
                <option value="Facebook">Facebook</option>
              </select>
            </label>
            <label>
              时长
              <select value={duration} onChange={(event) => changeDuration(Number(event.target.value) as 15 | 30)}>
                <option value={15}>15秒</option>
                <option value={30}>30秒</option>
              </select>
            </label>
            <label>
              画幅
              <input value="9:16" readOnly />
            </label>
          </div>

          <button type="button" onClick={() => void runPreflight()} disabled={preflightState === "loading"}>
            {preflightState === "loading" ? "Preflight检查中…" : "执行Provider-free Preflight"}
          </button>
          {preflightError && <p className="initial-video-project__error">{preflightError}</p>}

          {preflight && (
            <div className="initial-video-project__preflight">
              <strong>{preflight.ready_for_execution ? "READY" : "BLOCKED"}</strong>
              <dl>
                <div><dt>Product</dt><dd>#{preflight.product_id}</dd></div>
                <div><dt>Strategy</dt><dd>#{preflight.strategy_id}</dd></div>
                <div><dt>CopyMatrix</dt><dd>#{preflight.copy_matrix_id}</dd></div>
                <div><dt>有效期</dt><dd>{formatTime(preflight.expires_at)}</dd></div>
                <div><dt>Provider调用</dt><dd>{preflight.provider_calls}</dd></div>
                <div><dt>数据库写入</dt><dd>{preflight.database_writes}</dd></div>
              </dl>
              {preflight.missing_requirements.length > 0 && (
                <ul>
                  {preflight.missing_requirements.map((item) => (
                    <li key={item}>{MISSING_LABELS[item] ?? item}</li>
                  ))}
                </ul>
              )}
              <p>{preflight.cost_notice}</p>
            </div>
          )}

          {preflight?.ready_for_execution && videoProjectExecutionEnabled && !result && (
            <label className="initial-video-project__confirmation">
              <input
                type="checkbox"
                checked={costConfirmed}
                onChange={(event) => setCostConfirmed(event.target.checked)}
              />
              我明确确认本次一次Qwen VideoProject规划调用可能产生费用
            </label>
          )}
          {preflight?.ready_for_execution && !videoProjectExecutionEnabled && (
            <p>Frontend Gate默认关闭；当前只能查看Preflight，不能调用Qwen。</p>
          )}

          <button type="button" onClick={() => void execute()} disabled={!executeEnabled}>
            {executionState === "loading" ? "Qwen生成中…" : "确认费用并创建Video Blueprint"}
          </button>
          {executionError && <p className="initial-video-project__error">{executionError}</p>}

          {result && (
            <article className="initial-video-project__result">
              <span>{result.reused ? "EXACT RESULT REUSED" : "GENERATED"}</span>
              <h5>VideoProject #{result.generated_video_project.id}</h5>
              <p>{result.generated_video_project.title}</p>
              <dl>
                <div><dt>Strategy</dt><dd>#{result.strategy_id}</dd></div>
                <div><dt>CopyMatrix</dt><dd>#{result.copy_matrix_id}</dd></div>
                <div><dt>平台</dt><dd>{result.generated_video_project.platform}</dd></div>
                <div><dt>时长</dt><dd>{result.generated_video_project.duration_seconds}秒</dd></div>
              </dl>
              <p>精确VideoProject ID已传递给下方Wanx Render Preflight。</p>
            </article>
          )}
        </>
      )}
    </section>
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间无效" : date.toLocaleString("zh-CN");
}
