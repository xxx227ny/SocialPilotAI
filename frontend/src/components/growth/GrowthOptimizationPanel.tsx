import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  activateGrowthOptimizationRun,
  createGrowthOptimizationRun,
  executeGrowthOptimizationSandbox,
  listGrowthOptimizationExecutions,
  listGrowthOptimizationRuns,
  preflightGrowthOptimizationExecution,
  rollbackGrowthOptimizationExecution,
} from "../../api/growth";
import type {
  FeedbackContext,
  GrowthAnalysis,
  GrowthOptimizationExecution,
  GrowthOptimizationExecutionPreflight,
  GrowthOptimizationPolicy,
  GrowthOptimizationRun,
} from "../../types/growth";
import {
  activeOptimizationRun,
  canExecuteSandbox,
  canCreateOptimizationRun,
  canPreflightSandboxExecution,
  mergeOptimizationExecution,
  mergeOptimizationRun,
  optimizationIdempotencyKey,
  sandboxExecutionIdempotencyKey,
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
  const [executions, setExecutions] = useState<GrowthOptimizationExecution[]>([]);
  const [executionPreflight, setExecutionPreflight] =
    useState<GrowthOptimizationExecutionPreflight | null>(null);
  const [executionConfirmed, setExecutionConfirmed] = useState(false);
  const [executionKey, setExecutionKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const operation = useRef(0);

  useEffect(() => {
    const request = ++operation.current;
    const controller = new AbortController();
    setRuns([]);
    setExecutions([]);
    setExecutionPreflight(null);
    setExecutionConfirmed(false);
    setExecutionKey("");
    setMessage("");
    void Promise.all([
      listGrowthOptimizationRuns(productId, controller.signal),
      listGrowthOptimizationExecutions(productId, controller.signal),
    ])
      .then(([items, executionItems]) => {
        if (!controller.signal.aborted && request === operation.current) {
          setRuns(items);
          setExecutions(executionItems);
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
      setExecutionPreflight(null);
      setExecutionConfirmed(false);
      setExecutionKey("");
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

  async function preflightSandbox(run: GrowthOptimizationRun) {
    if (!canPreflightSandboxExecution(run, context, busy)) return;
    const request = ++operation.current;
    const controller = new AbortController();
    setBusy(true);
    setMessage("");
    setExecutionPreflight(null);
    setExecutionConfirmed(false);
    try {
      const checked = await preflightGrowthOptimizationExecution(
        productId,
        run.id,
        controller.signal,
      );
      if (request !== operation.current) return;
      setExecutionPreflight(checked);
      setExecutionKey(
        sandboxExecutionIdempotencyKey(run, context.context_digest, executions.length),
      );
      setMessage("沙箱执行Preflight已通过；请明确确认后执行。");
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "沙箱执行Preflight失败。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  async function executeSandbox(run: GrowthOptimizationRun) {
    if (
      !canExecuteSandbox(executionPreflight, executionConfirmed, busy) ||
      !executionKey
    ) {
      return;
    }
    const request = ++operation.current;
    const controller = new AbortController();
    setBusy(true);
    setMessage("");
    try {
      const result = await executeGrowthOptimizationSandbox(
        productId,
        run.id,
        executionKey,
        context.context_digest,
        controller.signal,
      );
      if (request !== operation.current) return;
      setExecutions((items) => mergeOptimizationExecution(items, result.execution));
      setMessage(
        result.reused
          ? `已恢复沙箱执行 #${result.execution.id}。`
          : `沙箱执行 #${result.execution.id} 已完成，真实广告平台未修改。`,
      );
      setExecutionPreflight(null);
      setExecutionConfirmed(false);
      setExecutionKey("");
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "沙箱执行失败。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  async function rollbackExecution(executionId: number) {
    if (busy) return;
    const request = ++operation.current;
    const controller = new AbortController();
    setBusy(true);
    setMessage("");
    try {
      const result = await rollbackGrowthOptimizationExecution(
        productId,
        executionId,
        controller.signal,
      );
      if (request !== operation.current) return;
      setExecutions((items) => mergeOptimizationExecution(items, result.execution));
      setMessage(
        result.reused
          ? `沙箱执行 #${executionId} 已经回滚。`
          : `已按精确Execution ID回滚 #${executionId}。`,
      );
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "沙箱回滚失败。"));
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
      <section className="growth-sandbox" aria-label="广告预算沙箱执行">
        <div className="growth-context-section-title">
          <strong>受控广告Adapter</strong>
          <small>SANDBOX · 不连接、不修改真实广告账户</small>
        </div>
        <button
          type="button"
          disabled={!canPreflightSandboxExecution(active, context, busy)}
          onClick={() => active && void preflightSandbox(active)}
        >
          运行沙箱执行Preflight
        </button>
        {executionPreflight && active && (
          <div className="growth-sandbox__confirm">
            <p>
              READY · Plan #{executionPreflight.optimization_run_id} · Provider {executionPreflight.provider_name}
            </p>
            <label>
              <input
                type="checkbox"
                checked={executionConfirmed}
                onChange={(event) => setExecutionConfirmed(event.target.checked)}
              />
              我确认仅执行SocialPilot AI沙箱方案，不会修改真实广告账户。
            </label>
            <button
              type="button"
              disabled={!canExecuteSandbox(executionPreflight, executionConfirmed, busy)}
              onClick={() => void executeSandbox(active)}
            >
              确认执行沙箱方案
            </button>
          </div>
        )}
        <p className="growth-panel__boundary">
          所有记录固定为SANDBOX；Provider调用0，external_mutation_performed=false。
        </p>
        {executions.length === 0 ? (
          <p>暂无沙箱执行记录。</p>
        ) : (
          executions.map((execution) => (
            <ExecutionCard
              key={execution.id}
              execution={execution}
              busy={busy}
              rollback={() => void rollbackExecution(execution.id)}
            />
          ))
        )}
      </section>
    </section>
  );
}

function NumberInput({ label, value, setValue }: { label: string; value: number; setValue: (value: number) => void }) {
  return <label><span>{label}</span><input type="number" min="0.01" step="0.01" value={value} onChange={(event) => setValue(Number(event.target.value))} /></label>;
}

function RunCard({ run, active = false, activate }: { run: GrowthOptimizationRun; active?: boolean; activate?: () => void }) {
  return <article className="growth-context-card"><header><strong>方案 #{run.id} · {run.status}</strong><small>{run.execution_scope} · 外部平台 {run.external_execution_status}</small></header><p>总预算 {run.recommended_total_budget.toFixed(2)}</p><ul>{run.actions.map((action) => <li key={action.platform}><strong>{action.platform}</strong>：预算 {action.recommended_budget.toFixed(2)} · 竞价 {signedPercent(action.bid_adjustment_pct)} · {action.action}</li>)}</ul>{!active && activate && <button type="button" onClick={activate}>按精确Plan ID激活</button>}</article>;
}

function ExecutionCard({ execution, busy, rollback }: { execution: GrowthOptimizationExecution; busy: boolean; rollback: () => void }) {
  return <article className="growth-context-card"><header><strong>Execution #{execution.id} · {execution.status}</strong><small>{execution.execution_mode} · {execution.provider_name}</small></header><p>真实平台修改：否 · Plan #{execution.optimization_run_id}</p><ul>{execution.result_actions.map((action) => <li key={action.platform}><strong>{action.platform}</strong>：结果预算 {action.recommended_budget.toFixed(2)} · 竞价 {signedPercent(action.bid_adjustment_pct)}</li>)}</ul>{execution.status === "SUCCEEDED" && <button type="button" disabled={busy} onClick={rollback}>按精确Execution ID回滚</button>}</article>;
}

function signedPercent(value: number) {
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}
