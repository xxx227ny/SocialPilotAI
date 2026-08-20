import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  activateGrowthOptimizationRun,
  createGrowthOptimizationRun,
  listGrowthOptimizationRuns,
} from "../../api/growth";
import type {
  FeedbackContext,
  GrowthAnalysis,
  GrowthOptimizationPolicy,
  GrowthOptimizationRun,
} from "../../types/growth";
import {
  activeOptimizationRun,
  canCreateOptimizationRun,
  mergeOptimizationRun,
  optimizationIdempotencyKey,
} from "./growthOptimizationState";

interface GrowthOptimizationPanelProps {
  productId: number;
  context: FeedbackContext;
  analysis: GrowthAnalysis | null;
  refreshContext: () => Promise<void>;
}

const DEFAULT_POLICY: GrowthOptimizationPolicy = {
  total_budget: 300,
  target_roas: 2,
  minimum_platform_share: 0.05,
  performance_tilt_share: 0.15,
  maximum_bid_adjustment_pct: 0.2,
};

export function GrowthOptimizationPanel({
  productId,
  context,
  analysis,
  refreshContext,
}: GrowthOptimizationPanelProps) {
  const [policy, setPolicy] = useState(DEFAULT_POLICY);
  const [runs, setRuns] = useState<GrowthOptimizationRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const operation = useRef(0);

  useEffect(() => {
    const request = ++operation.current;
    const controller = new AbortController();
    setRuns([]);
    setMessage("");
    void listGrowthOptimizationRuns(productId, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted && request === operation.current) {
          setRuns(items);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && request === operation.current) {
          setMessage(getApiErrorMessage(error, "优化方案历史读取失败。"));
        }
      });
    return () => controller.abort();
  }, [productId]);

  useEffect(() => {
    if (!autoRefresh) return;
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      await refreshContext();
      if (!stopped) timer = window.setTimeout(() => void tick(), 15_000);
    };
    timer = window.setTimeout(() => void tick(), 15_000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [autoRefresh, refreshContext]);

  async function createRun() {
    if (!canCreateOptimizationRun(analysis, context, policy, busy) || !analysis) {
      return;
    }
    const request = ++operation.current;
    const controller = new AbortController();
    setBusy(true);
    setMessage("");
    try {
      const result = await createGrowthOptimizationRun(
        productId,
        analysis,
        policy,
        optimizationIdempotencyKey(analysis, policy),
        controller.signal,
      );
      if (request !== operation.current) return;
      setRuns((items) => mergeOptimizationRun(items, result.run));
      setMessage(
        result.reused
          ? "已恢复相同优化方案。"
          : "已生成并激活系统内部预算/竞价方案。",
      );
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "优化方案生成失败。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  async function activate(runId: number) {
    if (busy) return;
    const request = ++operation.current;
    setBusy(true);
    setMessage("");
    try {
      const result = await activateGrowthOptimizationRun(productId, runId);
      if (request !== operation.current) return;
      const refreshed = await listGrowthOptimizationRuns(productId);
      if (request !== operation.current) return;
      setRuns(refreshed);
      setMessage(
        result.reused ? "该方案已经是当前方案。" : `已激活方案 #${runId}。`,
      );
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "历史方案激活失败。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  const active = activeOptimizationRun(runs);
  return (
    <section className="growth-recommendation" aria-label="ROAS预算竞价优化">
      <div className="growth-context-section-title">
        <strong>ROAS预算与竞价优化</strong>
        <small>Qwen建议 + 确定性分配 · 系统内部方案</small>
      </div>
      <label>
        <input
          type="checkbox"
          checked={autoRefresh}
          onChange={(event) => setAutoRefresh(event.target.checked)}
        />
        每15秒串行刷新ROAS Context
      </label>
      <div className="growth-panel__controls">
        <NumberInput label="总预算" value={policy.total_budget} setValue={(value) => setPolicy((old) => ({ ...old, total_budget: value }))} />
        <NumberInput label="目标ROAS" value={policy.target_roas} setValue={(value) => setPolicy((old) => ({ ...old, target_roas: value }))} />
        <button type="button" disabled={!canCreateOptimizationRun(analysis, context, policy, busy)} onClick={() => void createRun()}>
          {busy ? "处理中…" : "生成并自动激活内部方案"}
        </button>
      </div>
      {!analysis && <p>请先调用Qwen生成受约束Recommendation。</p>}
      {message && <p className="growth-panel__status">{message}</p>}
      <p className="growth-panel__boundary">
        当前仅更新SocialPilot AI内部方案；外部广告账户尚未连接，不代表平台预算已经修改。
      </p>
      {active && <RunCard run={active} active />}
      {runs.filter((item) => item.status !== "ACTIVE").map((run) => (
        <RunCard key={run.id} run={run} activate={() => void activate(run.id)} />
      ))}
    </section>
  );
}

function NumberInput({ label, value, setValue }: { label: string; value: number; setValue: (value: number) => void }) {
  return <label><span>{label}</span><input type="number" min="0.01" step="0.01" value={value} onChange={(event) => setValue(Number(event.target.value))} /></label>;
}

function RunCard({ run, active = false, activate }: { run: GrowthOptimizationRun; active?: boolean; activate?: () => void }) {
  return <article className="growth-context-card"><header><strong>方案 #{run.id} · {run.status}</strong><small>{run.execution_scope} · 外部平台 {run.external_execution_status}</small></header><p>总预算 {run.recommended_total_budget.toFixed(2)}</p><ul>{run.actions.map((action) => <li key={action.platform}><strong>{action.platform}</strong>：预算 {action.recommended_budget.toFixed(2)} · 竞价 {signedPercent(action.bid_adjustment_pct)} · {action.action}</li>)}</ul>{!active && activate && <button type="button" onClick={activate}>按精确Plan ID激活</button>}</article>;
}

function signedPercent(value: number) {
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}
