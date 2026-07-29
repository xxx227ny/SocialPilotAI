import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

import { getApiErrorMessage } from "../api/client";
import {
  executeGrowthRecommendation,
  getFeedbackContext,
  getGrowthRecommendationPreflight,
  uploadCampaignCsv,
} from "../api/growth";
import { growthExecutionEnabled } from "../config/features";
import type {
  CampaignMetrics,
  FeedbackContext,
  GrowthAnalysis,
  GrowthRecommendationPreflight,
} from "../types/growth";

interface GrowthCopilotPanelProps {
  productId: number;
}

type ContextState =
  | "loading"
  | "empty"
  | "ready"
  | "incomplete"
  | "error";
type PreflightState = "idle" | "checking" | "ready" | "blocked" | "failed";
type ExecutionState =
  | "idle"
  | "submitting"
  | "succeeded"
  | "failed"
  | "uncertain";

const MISSING_LABELS: Record<string, string> = {
  campaign_data: "Campaign投放数据",
  video_project: "VideoProject",
  marketing_strategy: "MarketingStrategy",
  copy_matrix: "CopyMatrix",
  exact_content_chain: "同一Product的精确内容链",
  supported_reference_platforms: "受支持的精确Copy/Video平台",
  provider_configuration: "Qwen Provider安全配置",
  growth_execution: "Backend Growth执行开关",
};

export function GrowthCopilotPanel({ productId }: GrowthCopilotPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [context, setContext] = useState<FeedbackContext | null>(null);
  const [contextState, setContextState] =
    useState<ContextState>("loading");
  const [contextError, setContextError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [reading, setReading] = useState(false);
  const [preflight, setPreflight] =
    useState<GrowthRecommendationPreflight | null>(null);
  const [preflightState, setPreflightState] =
    useState<PreflightState>("idle");
  const [preflightError, setPreflightError] = useState("");
  const [feeConfirmed, setFeeConfirmed] = useState(false);
  const [authorizationConsumed, setAuthorizationConsumed] =
    useState(false);
  const [executionState, setExecutionState] =
    useState<ExecutionState>("idle");
  const [executionError, setExecutionError] = useState("");
  const [recommendationResult, setRecommendationResult] =
    useState<GrowthAnalysis | null>(null);
  const currentProductId = useRef(productId);
  const contextRequestId = useRef(0);
  const uploadRequestId = useRef(0);
  const contextController = useRef<AbortController | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const preflightController = useRef<AbortController | null>(null);
  const executionController = useRef<AbortController | null>(null);
  const preflightRequestId = useRef(0);
  const executionRequestId = useRef(0);
  const manualReadLock = useRef(false);
  const uploadLock = useRef(false);
  const preflightLock = useRef(false);
  const executionLock = useRef(false);
  const authorizationConsumedRef = useRef(false);

  const resetRecommendation = useCallback(() => {
    preflightRequestId.current += 1;
    executionRequestId.current += 1;
    preflightController.current?.abort();
    executionController.current?.abort();
    preflightLock.current = false;
    executionLock.current = false;
    authorizationConsumedRef.current = false;
    setPreflight(null);
    setPreflightState("idle");
    setPreflightError("");
    setFeeConfirmed(false);
    setAuthorizationConsumed(false);
    setExecutionState("idle");
    setExecutionError("");
    setRecommendationResult(null);
  }, []);

  const readContext = useCallback(
    async (expectedProductId: number, manual: boolean) => {
      if (
        manual &&
        (manualReadLock.current || executionLock.current)
      ) {
        return;
      }
      if (manual) manualReadLock.current = true;

      const requestId = ++contextRequestId.current;
      const controller = new AbortController();
      contextController.current?.abort();
      contextController.current = controller;
      setReading(manual);
      setContextState("loading");
      setContextError("");

      try {
        const result = await getFeedbackContext(
          expectedProductId,
          controller.signal,
        );
        if (
          controller.signal.aborted ||
          requestId !== contextRequestId.current ||
          currentProductId.current !== expectedProductId ||
          result.product_id !== expectedProductId
        ) {
          return;
        }
        resetRecommendation();
        setContext(result);
        setContextState(
          result.campaign_count === 0
            ? "empty"
            : result.context_ready
              ? "ready"
              : "incomplete",
        );
      } catch (error) {
        if (
          controller.signal.aborted ||
          requestId !== contextRequestId.current ||
          currentProductId.current !== expectedProductId
        ) {
          return;
        }
        setContext(null);
        setContextState("error");
        setContextError(
          getApiErrorMessage(
            error,
            "FeedbackContext读取失败，请检查Backend连接后重试。",
          ),
        );
      } finally {
        if (requestId === contextRequestId.current) {
          setReading(false);
        }
        if (manual) manualReadLock.current = false;
      }
    },
    [resetRecommendation],
  );

  useEffect(() => {
    currentProductId.current = productId;
    setFile(null);
    setNotice("");
    setContext(null);
    setContextError("");
    resetRecommendation();
    uploadRequestId.current += 1;
    uploadController.current?.abort();
    uploadLock.current = false;
    setUploading(false);
    void readContext(productId, false);

    return () => {
      contextController.current?.abort();
      uploadController.current?.abort();
      preflightController.current?.abort();
      executionController.current?.abort();
    };
  }, [productId, readContext, resetRecommendation]);

  async function handleUpload() {
    if (!file || uploadLock.current || executionLock.current) return;
    uploadLock.current = true;
    const expectedProductId = productId;
    const requestId = ++uploadRequestId.current;
    const controller = new AbortController();
    uploadController.current?.abort();
    uploadController.current = controller;
    setUploading(true);
    setNotice("");
    resetRecommendation();

    try {
      const result = await uploadCampaignCsv(
        expectedProductId,
        file,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== uploadRequestId.current ||
        currentProductId.current !== expectedProductId ||
        result.product_id !== expectedProductId
      ) {
        return;
      }
      setNotice(
        `已导入${result.imported_count}条Campaign记录；本操作未调用AI。`,
      );
      setFile(null);
      await readContext(expectedProductId, false);
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== uploadRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      setNotice(
        getApiErrorMessage(
          error,
          "Campaign CSV导入失败，请检查字段、格式和数据范围。",
        ),
      );
    } finally {
      if (requestId === uploadRequestId.current) {
        setUploading(false);
        uploadLock.current = false;
      }
    }
  }

  async function handlePreflight() {
    if (
      !context ||
      preflightLock.current ||
      executionLock.current
    ) {
      return;
    }
    preflightLock.current = true;
    const expectedProductId = productId;
    const expectedContext = context;
    const requestId = ++preflightRequestId.current;
    const controller = new AbortController();
    preflightController.current?.abort();
    preflightController.current = controller;
    setPreflightState("checking");
    setPreflightError("");
    setFeeConfirmed(false);
    setExecutionState("idle");
    setExecutionError("");
    setRecommendationResult(null);
    try {
      const result = await getGrowthRecommendationPreflight(
        expectedProductId,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== preflightRequestId.current ||
        currentProductId.current !== expectedProductId ||
        !samePreflightIdentity(result, expectedContext)
      ) {
        return;
      }
      setPreflight(result);
      setPreflightState(result.ready_for_execution ? "ready" : "blocked");
      authorizationConsumedRef.current = false;
      setAuthorizationConsumed(false);
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== preflightRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      setPreflight(null);
      setPreflightState("failed");
      setPreflightError(
        getApiErrorMessage(
          error,
          "Recommendation Preflight失败，请恢复Backend后重试。",
        ),
      );
    } finally {
      if (requestId === preflightRequestId.current) {
        preflightLock.current = false;
      }
    }
  }

  const canExecute = Boolean(
    growthExecutionEnabled &&
      context?.context_ready &&
      preflightState === "ready" &&
      preflight?.ready_for_execution &&
      preflight &&
      context &&
      samePreflightIdentity(preflight, context) &&
      feeConfirmed &&
      !authorizationConsumed &&
      executionState !== "submitting",
  );

  async function handleExecuteRecommendation() {
    if (
      !canExecute ||
      !context ||
      !preflight ||
      executionLock.current ||
      authorizationConsumedRef.current
    ) {
      return;
    }
    executionLock.current = true;
    authorizationConsumedRef.current = true;
    setAuthorizationConsumed(true);
    setFeeConfirmed(false);
    const expectedProductId = productId;
    const expectedContext = context;
    const requestId = ++executionRequestId.current;
    const controller = new AbortController();
    executionController.current?.abort();
    executionController.current = controller;
    setExecutionState("submitting");
    setExecutionError("");
    setRecommendationResult(null);
    try {
      const result = await executeGrowthRecommendation(
        expectedProductId,
        expectedContext.context_digest,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        requestId !== executionRequestId.current ||
        currentProductId.current !== expectedProductId ||
        !sameExecutionIdentity(result, expectedContext)
      ) {
        return;
      }
      setRecommendationResult(result);
      setExecutionState("succeeded");
      setPreflight(null);
      setPreflightState("idle");
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestId !== executionRequestId.current ||
        currentProductId.current !== expectedProductId
      ) {
        return;
      }
      const uncertain =
        axios.isAxiosError(error) &&
        (!error.response || error.response.status === 503);
      setExecutionState(uncertain ? "uncertain" : "failed");
      setExecutionError(
        uncertain
          ? "执行结果不确定；不会自动重试。重新执行前必须重新Preflight并确认费用。"
          : getApiErrorMessage(
              error,
              "Recommendation执行失败；不会自动重试。",
            ),
      );
      setPreflight(null);
      setPreflightState("idle");
      setFeeConfirmed(false);
    } finally {
      if (requestId === executionRequestId.current) {
        executionLock.current = false;
      }
    }
  }

  return (
    <section className="growth-panel" aria-label="Structured FeedbackContext">
      <div className="growth-panel__header">
        <div>
          <span>STRUCTURED FEEDBACK CONTEXT</span>
          <strong>投放反馈上下文</strong>
        </div>
        <div className="growth-panel__zero-ai">
          <strong>
            {recommendationResult?.provider_calls ?? 0} AI Calls
          </strong>
          <small>Context读取始终Provider-free</small>
        </div>
      </div>

      <div className="growth-panel__controls">
        <label>
          <input
            accept=".csv,text/csv"
            type="file"
            disabled={uploading || executionState === "submitting"}
            onChange={(event) =>
              setFile(event.target.files?.[0] ?? null)
            }
          />
          <span>{file?.name ?? "选择Campaign CSV"}</span>
        </label>
        <button
          type="button"
          disabled={
            !file ||
            uploading ||
            executionState === "submitting"
          }
          onClick={() => void handleUpload()}
        >
          {uploading ? "导入中…" : "导入Campaign CSV"}
        </button>
        <button
          type="button"
          disabled={
            reading ||
            contextState === "loading" ||
            executionState === "submitting"
          }
          onClick={() => void readContext(productId, true)}
        >
          {reading ? "读取中…" : "重新读取FeedbackContext"}
        </button>
      </div>
      <p className="growth-panel__boundary">
        CSV导入会追加Campaign记录，但不会调用AI；重复导入当前不会自动去重或替换。
      </p>
      {notice && <p className="growth-panel__status">{notice}</p>}

      {contextState === "loading" && (
        <ContextMessage
          title="正在读取FeedbackContext"
          detail="正在从本地持久化Campaign与精确内容链构建确定性快照。"
        />
      )}
      {contextState === "error" && (
        <ContextMessage
          title="FeedbackContext读取失败"
          detail={contextError}
          error
        />
      )}
      {contextState === "empty" && context && (
        <ContextMessage
          title="尚无Campaign数据"
          detail="Context已安全返回；请主动导入合法CSV。系统不会自动上传或调用AI。"
        />
      )}
      {(contextState === "ready" || contextState === "incomplete") &&
        context && <ContextResult context={context} />}

      <section
        className="growth-recommendation"
        aria-label="Recommendation Constraints"
      >
        <div className="growth-context-section-title">
          <strong>Recommendation-to-Generation Constraints</strong>
          <small>只生成测试假设与后续生成约束</small>
        </div>
        <div className="growth-recommendation__actions">
          <button
            type="button"
            disabled={
              !context ||
              preflightState === "checking" ||
              executionState === "submitting"
            }
            onClick={() => void handlePreflight()}
          >
            {preflightState === "checking"
              ? "检查中…"
              : "运行Recommendation Preflight"}
          </button>
          <span>
            Frontend Gate：
            {growthExecutionEnabled ? "已开启" : "默认关闭"}
          </span>
        </div>

        {preflightState === "idle" && (
          <ContextMessage
            title="尚未运行Preflight"
            detail="这是只读检查，不调用Provider、不写数据库。"
          />
        )}
        {preflightState === "checking" && (
          <ContextMessage
            title="正在运行Recommendation Preflight"
            detail="正在重新核对Product、Context Digest与原子内容链。"
          />
        )}
        {preflightState === "failed" && (
          <ContextMessage
            title="Recommendation Preflight失败"
            detail={preflightError}
            error
          />
        )}
        {(preflightState === "ready" ||
          preflightState === "blocked") &&
          preflight && (
            <PreflightResult
              preflight={preflight}
              state={preflightState}
            />
          )}

        <label className="growth-recommendation__confirm">
          <input
            type="checkbox"
            checked={feeConfirmed}
            disabled={
              preflightState !== "ready" ||
              authorizationConsumed ||
              executionState === "submitting"
            }
            onChange={(event) => setFeeConfirmed(event.target.checked)}
          />
          <span>
            我确认本次Recommendation会调用Qwen，可能产生费用；失败或不确定后不会自动重试。
          </span>
        </label>
        <button
          className="growth-recommendation__execute"
          type="button"
          disabled={!canExecute}
          onClick={() => void handleExecuteRecommendation()}
        >
          {executionState === "submitting"
            ? "正在生成受约束Recommendation…"
            : "调用Qwen生成受约束Recommendation"}
        </button>
        {executionState === "failed" && (
          <ContextMessage
            title="Recommendation执行失败"
            detail={executionError}
            error
          />
        )}
        {executionState === "uncertain" && (
          <ContextMessage
            title="Recommendation执行结果不确定"
            detail={executionError}
            error
          />
        )}
        {executionState === "succeeded" && recommendationResult && (
          <RecommendationResult result={recommendationResult} />
        )}

        <p className="growth-panel__boundary">
          Recommendation不持久化；页面刷新后可能丢失。再次执行可能再次产生Provider费用。
          C4.2必须重新验证Product、Digest和精确内容链。
        </p>
        <div className="growth-recommendation__future">
          <button type="button" disabled>
            C4.2A 生成V2 Copy（未开放）
          </button>
          <button type="button" disabled>
            C4.2B 生成V2 VideoProject（未开放）
          </button>
        </div>
      </section>
    </section>
  );
}

function ContextMessage({
  title,
  detail,
  error = false,
}: {
  title: string;
  detail: string;
  error?: boolean;
}) {
  return (
    <div
      className={`growth-context-state${
        error ? " growth-context-state--error" : ""
      }`}
    >
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function ContextResult({ context }: { context: FeedbackContext }) {
  return (
    <div className="growth-context-result">
      <div className="growth-context-summary">
        <div>
          <small>Context readiness</small>
          <strong>
            {context.context_ready ? "READY" : "INCOMPLETE"}
          </strong>
        </div>
        <div>
          <small>Campaign</small>
          <strong>{context.campaign_count}条</strong>
        </div>
        <div>
          <small>日期范围</small>
          <strong>
            {context.date_from && context.date_to
              ? `${context.date_from} — ${context.date_to}`
              : "尚无日期"}
          </strong>
        </div>
        <div>
          <small>Context Digest</small>
          <strong title={context.context_digest}>
            {context.context_digest.slice(0, 12)}…
          </strong>
        </div>
      </div>

      {context.overall_metrics && (
        <>
          <div className="growth-context-section-title">
            <strong>总体指标</strong>
            <small>先聚合总量，再计算比率</small>
          </div>
          <MetricsGrid metrics={context.overall_metrics} />
        </>
      )}

      <div className="growth-context-platforms">
        {context.platform_metrics.map((item) => (
          <article key={item.platform}>
            <strong>{item.platform}</strong>
            <MetricsGrid metrics={item.metrics} compact />
          </article>
        ))}
      </div>

      {context.content_chain_ready ? (
        <div className="growth-context-chain">
          <div>
            <small>MarketingStrategy</small>
            <strong>{asId(context.marketing_strategy_id)}</strong>
          </div>
          <div>
            <small>CopyMatrix</small>
            <strong>{asId(context.copy_matrix_id)}</strong>
          </div>
          <div>
            <small>VideoProject</small>
            <strong>{asId(context.video_project_id)}</strong>
          </div>
          <p>
            精确选择：latest VideoProject → 它引用的CopyMatrix与MarketingStrategy
          </p>
        </div>
      ) : (
        <div className="growth-context-chain">
          <strong>精确内容链未就绪</strong>
          <p>仅在完整链通过当前Product身份和引用一致性校验后显示内容ID。</p>
        </div>
      )}

      {context.missing_requirements.length > 0 && (
        <div className="growth-context-missing">
          <strong>Missing requirements</strong>
          <ul>
            {context.missing_requirements.map((item) => (
              <li key={item}>{MISSING_LABELS[item] ?? item}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="growth-context-attribution">
        产品级归因边界：Campaign指标只能归属于当前Product，不能证明由当前CopyMatrix、
        VideoProject或Artifact产生。当前内容链仅是下一阶段的精确参考链；
        VideoProject没有MarketingBrief外键。
      </p>
    </div>
  );
}

function PreflightResult({
  preflight,
  state,
}: {
  preflight: GrowthRecommendationPreflight;
  state: "ready" | "blocked";
}) {
  return (
    <div className="growth-recommendation__preflight">
      <div className="growth-context-summary">
        <div>
          <small>Preflight</small>
          <strong>{state === "ready" ? "READY" : "BLOCKED"}</strong>
        </div>
        <div>
          <small>Input</small>
          <strong>{preflight.input_ready ? "READY" : "BLOCKED"}</strong>
        </div>
        <div>
          <small>Provider配置</small>
          <strong>
            {preflight.provider_configured ? "已配置" : "未配置"}
          </strong>
        </div>
        <div>
          <small>Backend Gate</small>
          <strong>
            {preflight.execution_enabled ? "已开启" : "默认关闭"}
          </strong>
        </div>
      </div>
      <p>{preflight.cost_notice}</p>
      <p>{preflight.attribution_notice}</p>
      {preflight.missing_requirements.length > 0 && (
        <div className="growth-context-missing">
          <strong>Blocked requirements</strong>
          <ul>
            {preflight.missing_requirements.map((item) => (
              <li key={item}>{MISSING_LABELS[item] ?? item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RecommendationResult({ result }: { result: GrowthAnalysis }) {
  const recommendation = result.recommendation;
  return (
    <div className="growth-recommendation__result">
      <div className="growth-context-section-title">
        <strong>本次受约束Recommendation</strong>
        <small>
          Context {result.source_context_digest.slice(0, 12)}… · Strategy #
          {result.source_marketing_strategy_id} · CopyMatrix #
          {result.source_copy_matrix_id} · VideoProject #
          {result.source_video_project_id}
        </small>
      </div>
      <p>{recommendation.summary}</p>

      <h5>Observations · 测试假设</h5>
      <div className="growth-recommendation__cards">
        {recommendation.observations.map((item, index) => (
          <article
            key={`${item.scope}-${item.platform ?? "overall"}-${item.metric}-${index}`}
          >
            <strong>
              {item.platform ?? "Overall"} · {item.metric}
            </strong>
            <small>{item.direction}</small>
            <p>{item.hypothesis}</p>
          </article>
        ))}
      </div>

      <h5>Copy constraints</h5>
      <div className="growth-recommendation__cards">
        {recommendation.copy_constraints.map((item) => (
          <article key={item.platform}>
            <strong>{item.platform}</strong>
            <p>Hook：{item.hook_direction}</p>
            <p>Angle：{item.message_angle}</p>
            <p>CTA：{item.cta_direction}</p>
            <p>保留：{item.must_preserve.join("；")}</p>
            <p>避免：{item.must_avoid.join("；")}</p>
          </article>
        ))}
      </div>

      <h5>Video constraint</h5>
      <article className="growth-recommendation__video">
        <strong>{recommendation.video_constraint.platform}</strong>
        <p>Opening：{recommendation.video_constraint.opening_hook_direction}</p>
        <p>Visual：{recommendation.video_constraint.visual_focus}</p>
        <p>Pacing：{recommendation.video_constraint.pacing_direction}</p>
        <p>CTA：{recommendation.video_constraint.cta_direction}</p>
      </article>

      <h5>Budget guidance</h5>
      <p>{recommendation.budget_guidance}</p>
      <p className="growth-context-attribution">
        Product级数据形成的测试假设，不是创意因果证明。本次结果未持久化、
        未修改预算、未生成V2 Copy或VideoProject，也没有自动执行权限。
      </p>
    </div>
  );
}

function MetricsGrid({
  metrics,
  compact = false,
}: {
  metrics: CampaignMetrics;
  compact?: boolean;
}) {
  return (
    <div
      className={`growth-metrics${
        compact ? " growth-metrics--compact" : ""
      }`}
    >
      <Metric label="CTR" value={asPercent(metrics.ctr)} />
      <Metric
        label="CVR"
        value={asPercent(metrics.conversion_rate)}
      />
      <Metric label="CPA" value={asCurrency(metrics.cpa)} />
      <Metric label="ROAS" value={asRatio(metrics.roas)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function asId(value: number | null) {
  return value === null ? "未就绪" : `#${value}`;
}

function asPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function asCurrency(value: number | null) {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

function asRatio(value: number | null) {
  return value === null ? "—" : `${value.toFixed(2)}x`;
}

function samePreflightIdentity(
  preflight: GrowthRecommendationPreflight,
  context: FeedbackContext,
) {
  return (
    preflight.product_id === context.product_id &&
    preflight.context_digest === context.context_digest &&
    preflight.marketing_strategy_id === context.marketing_strategy_id &&
    preflight.copy_matrix_id === context.copy_matrix_id &&
    preflight.video_project_id === context.video_project_id
  );
}

function sameExecutionIdentity(
  result: GrowthAnalysis,
  context: FeedbackContext,
) {
  return (
    result.product_id === context.product_id &&
    result.source_context_digest === context.context_digest &&
    result.source_marketing_strategy_id ===
      context.marketing_strategy_id &&
    result.source_copy_matrix_id === context.copy_matrix_id &&
    result.source_video_project_id === context.video_project_id
  );
}
