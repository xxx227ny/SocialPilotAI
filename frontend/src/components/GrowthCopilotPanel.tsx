import { useCallback, useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../api/client";
import {
  getFeedbackContext,
  uploadCampaignCsv,
} from "../api/growth";
import type {
  CampaignMetrics,
  FeedbackContext,
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

const MISSING_LABELS: Record<string, string> = {
  campaign_data: "Campaign投放数据",
  video_project: "VideoProject",
  marketing_strategy: "MarketingStrategy",
  copy_matrix: "CopyMatrix",
  exact_content_chain: "同一Product的精确内容链",
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
  const currentProductId = useRef(productId);
  const contextRequestId = useRef(0);
  const uploadRequestId = useRef(0);
  const contextController = useRef<AbortController | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const manualReadLock = useRef(false);
  const uploadLock = useRef(false);

  const readContext = useCallback(
    async (expectedProductId: number, manual: boolean) => {
      if (manual && manualReadLock.current) return;
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
    [],
  );

  useEffect(() => {
    currentProductId.current = productId;
    setFile(null);
    setNotice("");
    setContext(null);
    setContextError("");
    uploadRequestId.current += 1;
    uploadController.current?.abort();
    uploadLock.current = false;
    setUploading(false);
    void readContext(productId, false);

    return () => {
      contextController.current?.abort();
      uploadController.current?.abort();
    };
  }, [productId, readContext]);

  async function handleUpload() {
    if (!file || uploadLock.current) return;
    uploadLock.current = true;
    const expectedProductId = productId;
    const requestId = ++uploadRequestId.current;
    const controller = new AbortController();
    uploadController.current?.abort();
    uploadController.current = controller;
    setUploading(true);
    setNotice("");

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

  return (
    <section className="growth-panel" aria-label="Structured FeedbackContext">
      <div className="growth-panel__header">
        <div>
          <span>STRUCTURED FEEDBACK CONTEXT</span>
          <strong>投放反馈上下文</strong>
        </div>
        <div className="growth-panel__zero-ai">
          <strong>0 AI Calls</strong>
          <small>确定性只读聚合</small>
        </div>
      </div>

      <div className="growth-panel__controls">
        <label>
          <input
            accept=".csv,text/csv"
            type="file"
            disabled={uploading}
            onChange={(event) =>
              setFile(event.target.files?.[0] ?? null)
            }
          />
          <span>{file?.name ?? "选择Campaign CSV"}</span>
        </label>
        <button
          type="button"
          disabled={!file || uploading}
          onClick={() => void handleUpload()}
        >
          {uploading ? "导入中…" : "导入Campaign CSV"}
        </button>
        <button
          type="button"
          disabled={reading || contextState === "loading"}
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

      <button
        className="growth-panel__future-action"
        type="button"
        disabled
      >
        AI优化建议将在后续受控阶段开放
      </button>
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
