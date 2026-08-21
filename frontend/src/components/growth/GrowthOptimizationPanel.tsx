import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  activateGrowthOptimizationRun,
  createGrowthOptimizationRun,
  engageGrowthAutomationKillSwitch,
  evaluateGrowthAutomation,
  executeGrowthOptimizationSandbox,
  getGrowthAutomationControl,
  listGrowthOptimizationExecutions,
  listGrowthAutomationCycles,
  listGrowthOptimizationRuns,
  preflightGrowthOptimizationExecution,
  rollbackGrowthOptimizationExecution,
  runGrowthAutomationCycle,
  updateGrowthAutomationControl,
} from "../../api/growth";
import type {
  FeedbackContext,
  GrowthAnalysis,
  GrowthAutomationControl,
  GrowthAutomationControlUpdate,
  GrowthAutomationCycle,
  GrowthOptimizationExecution,
  GrowthOptimizationExecutionPreflight,
  GrowthOptimizationPolicy,
  GrowthOptimizationRun,
} from "../../types/growth";
import {
  activeOptimizationRun,
  automationEvaluationIdempotencyKey,
  canEvaluateAutomation,
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

const DEFAULT_AUTOMATION: GrowthAutomationControlUpdate = {
  mode: "MANUAL",
  kill_switch_engaged: true,
  maximum_total_budget: 1000,
  maximum_budget_change_pct: 0.25,
  maximum_bid_adjustment_pct: 0.2,
  monitoring_enabled: false,
  evaluation_interval_seconds: 900,
  confirm_auto_sandbox: false,
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
  const [automation, setAutomation] = useState<GrowthAutomationControl | null>(null);
  const [cycles, setCycles] = useState<GrowthAutomationCycle[]>([]);
  const [automationDraft, setAutomationDraft] =
    useState<GrowthAutomationControlUpdate>(DEFAULT_AUTOMATION);
  const [automationConfirmed, setAutomationConfirmed] = useState(false);
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
    setAutomation(null);
    setCycles([]);
    setAutomationDraft(DEFAULT_AUTOMATION);
    setAutomationConfirmed(false);
    setExecutionPreflight(null);
    setExecutionConfirmed(false);
    setExecutionKey("");
    setMessage("");
    void Promise.all([
      listGrowthOptimizationRuns(productId, controller.signal),
      listGrowthOptimizationExecutions(productId, controller.signal),
      getGrowthAutomationControl(productId, controller.signal),
      listGrowthAutomationCycles(productId, controller.signal),
    ])
      .then(([items, executionItems, automationControl, cycleItems]) => {
        if (!controller.signal.aborted && request === operation.current) {
          setRuns(items);
          setExecutions(executionItems);
          setAutomation(automationControl);
          setCycles(cycleItems);
          setAutomationDraft({
            mode: automationControl.mode,
            kill_switch_engaged: automationControl.kill_switch_engaged,
            maximum_total_budget: automationControl.maximum_total_budget,
            maximum_budget_change_pct:
              automationControl.maximum_budget_change_pct,
            maximum_bid_adjustment_pct:
              automationControl.maximum_bid_adjustment_pct,
            monitoring_enabled: automationControl.monitoring_enabled,
            evaluation_interval_seconds:
              automationControl.evaluation_interval_seconds,
            confirm_auto_sandbox: false,
          });
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

  async function saveAutomation() {
    if (
      busy ||
      (automationDraft.mode === "AUTO_SANDBOX" &&
        !automationDraft.kill_switch_engaged &&
        !automationConfirmed)
    ) {
      return;
    }
    const request = ++operation.current;
    const controller = new AbortController();
    setBusy(true);
    setMessage("");
    try {
      const saved = await updateGrowthAutomationControl(
        productId,
        {
          ...automationDraft,
          confirm_auto_sandbox: automationConfirmed,
        },
        controller.signal,
      );
      if (request !== operation.current) return;
      setAutomation(saved);
      setAutomationDraft((current) => ({
        ...current,
        mode: saved.mode,
        kill_switch_engaged: saved.kill_switch_engaged,
        confirm_auto_sandbox: false,
      }));
      setAutomationConfirmed(false);
      setMessage(
        saved.mode === "AUTO_SANDBOX" && !saved.kill_switch_engaged
          ? "AUTO_SANDBOX已启用；所有动作仍只进入本地沙箱。"
          : "自动化控制已保存，当前不会自动执行。",
      );
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "自动化控制保存失败。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  async function engageKillSwitch() {
    if (busy) return;
    const request = ++operation.current;
    setBusy(true);
    setMessage("");
    try {
      const stopped = await engageGrowthAutomationKillSwitch(productId);
      if (request !== operation.current) return;
      setAutomation(stopped);
      setAutomationDraft((current) => ({
        ...current,
        mode: stopped.mode,
        kill_switch_engaged: true,
        confirm_auto_sandbox: false,
      }));
      setAutomationConfirmed(false);
      setMessage("Kill Switch已开启；后续自动评估全部阻断。现有历史不会删除。");
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "Kill Switch操作失败。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  async function evaluateAutomation() {
    if (!canEvaluateAutomation(automation, active, context, busy) || !active) {
      return;
    }
    const request = ++operation.current;
    setBusy(true);
    setMessage("");
    try {
      const result = await evaluateGrowthAutomation(
        productId,
        automationEvaluationIdempotencyKey(
          active,
          context.context_digest,
          executions.length,
        ),
        context.context_digest,
      );
      if (request !== operation.current) return;
      setExecutions((items) => mergeOptimizationExecution(items, result.execution));
      setAutomation(await getGrowthAutomationControl(productId));
      if (request !== operation.current) return;
      setMessage(
        result.reused
          ? `已恢复自动沙箱Execution #${result.execution.id}。`
          : `自动策略已通过全部上限并完成Execution #${result.execution.id}；真实平台未修改。`,
      );
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "自动沙箱评估被安全门禁阻断。"));
      }
    } finally {
      if (request === operation.current) setBusy(false);
    }
  }

  async function runMonitoringCycle() {
    if (busy || !automation?.monitoring_enabled) return;
    const request = ++operation.current;
    setBusy(true);
    setMessage("");
    try {
      const result = await runGrowthAutomationCycle(productId, true);
      if (request !== operation.current) return;
      if (result.cycle) {
        setCycles((items) => [
          result.cycle as GrowthAutomationCycle,
          ...items.filter((item) => item.id !== result.cycle?.id),
        ]);
      }
      const [saved, executionItems] = await Promise.all([
        getGrowthAutomationControl(productId),
        listGrowthOptimizationExecutions(productId),
      ]);
      if (request !== operation.current) return;
      setAutomation(saved);
      setExecutions(executionItems);
      setMessage(
        result.cycle
          ? `监控周期 #${result.cycle.id}：${result.cycle.status}；Provider调用0，真实广告修改0。`
          : "当前周期尚未到期，没有写入审计记录。",
      );
    } catch (error) {
      if (request === operation.current) {
        setMessage(getApiErrorMessage(error, "监控周期被安全门禁阻断。"));
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
        <section className="growth-automation" aria-label="自动模式与安全上限">
          <div className="growth-context-section-title">
            <strong>自动模式与安全上限</strong>
            <small>
              {automation?.mode ?? "MANUAL"} · Kill Switch
              {automation?.kill_switch_engaged ?? true ? "已开启" : "已关闭"}
            </small>
          </div>
          <label>
            <span>运行模式</span>
            <select
              aria-label="运行模式"
              value={automationDraft.mode}
              onChange={(event) => {
                setAutomationDraft((current) => ({
                  ...current,
                  mode: event.target.value as "MANUAL" | "AUTO_SANDBOX",
                }));
                setAutomationConfirmed(false);
              }}
            >
              <option value="MANUAL">MANUAL</option>
              <option value="AUTO_SANDBOX">AUTO_SANDBOX</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={automationDraft.kill_switch_engaged}
              onChange={(event) => {
                setAutomationDraft((current) => ({
                  ...current,
                  kill_switch_engaged: event.target.checked,
                }));
                setAutomationConfirmed(false);
              }}
            />
            Kill Switch保持开启
          </label>
          <label>
            <input
              type="checkbox"
              checked={automationDraft.monitoring_enabled}
              onChange={(event) =>
                setAutomationDraft((current) => ({
                  ...current,
                  monitoring_enabled: event.target.checked,
                }))
              }
            />
            启用持久化ROAS监控计划
          </label>
          <NumberInput
            label="监控间隔（秒）"
            value={automationDraft.evaluation_interval_seconds}
            setValue={(value) =>
              setAutomationDraft((current) => ({
                ...current,
                evaluation_interval_seconds: value,
              }))
            }
          />
          <div className="growth-automation__limits">
            <NumberInput
              label="自动总预算上限"
              value={automationDraft.maximum_total_budget}
              setValue={(value) =>
                setAutomationDraft((current) => ({
                  ...current,
                  maximum_total_budget: value,
                }))
              }
            />
            <NumberInput
              label="单平台预算变动上限"
              value={automationDraft.maximum_budget_change_pct}
              setValue={(value) =>
                setAutomationDraft((current) => ({
                  ...current,
                  maximum_budget_change_pct: value,
                }))
              }
            />
            <NumberInput
              label="竞价调整上限"
              value={automationDraft.maximum_bid_adjustment_pct}
              setValue={(value) =>
                setAutomationDraft((current) => ({
                  ...current,
                  maximum_bid_adjustment_pct: value,
                }))
              }
            />
          </div>
          {automationDraft.mode === "AUTO_SANDBOX" &&
            !automationDraft.kill_switch_engaged && (
              <label className="growth-sandbox__confirm">
                <input
                  type="checkbox"
                  checked={automationConfirmed}
                  onChange={(event) =>
                    setAutomationConfirmed(event.target.checked)
                  }
                />
                我确认自动模式仅运行SocialPilot AI沙箱，不会修改真实广告账户。
              </label>
            )}
          <div className="growth-automation__actions">
            <button
              type="button"
              disabled={
                busy ||
                (automationDraft.mode === "AUTO_SANDBOX" &&
                  !automationDraft.kill_switch_engaged &&
                  !automationConfirmed)
              }
              onClick={() => void saveAutomation()}
            >
              保存自动化控制
            </button>
            <button
              type="button"
              disabled={busy || Boolean(automation?.kill_switch_engaged)}
              onClick={() => void engageKillSwitch()}
            >
              立即开启Kill Switch
            </button>
            <button
              type="button"
              disabled={!canEvaluateAutomation(automation, active, context, busy)}
              onClick={() => void evaluateAutomation()}
            >
              运行一次自动策略评估
            </button>
            <button
              type="button"
              disabled={busy || !automation?.monitoring_enabled}
              onClick={() => void runMonitoringCycle()}
            >
              立即运行一次监控周期
            </button>
          </div>
          <p className="growth-panel__boundary">
            周期Runner需由外部调度器按次启动；数据变化时只记录REPLAN_REQUIRED，不会偷偷调用Qwen。AUTO_SANDBOX仍不连接广告平台。
          </p>
          <div aria-label="ROAS监控周期历史">
            {cycles.length === 0 ? (
              <p>暂无监控周期记录。</p>
            ) : (
              cycles.map((cycle) => (
                <p key={cycle.id}>
                  周期 #{cycle.id} · {cycle.status} · Plan {cycle.optimization_run_id ?? "无"} · Execution {cycle.execution_id ?? "无"} · Provider 0 · 外部修改 否
                </p>
              ))
            )}
          </div>
        </section>
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
  return <article className="growth-context-card"><header><strong>Execution #{execution.id} · {execution.status}</strong><small>{execution.execution_mode} · {execution.provider_name} · {execution.trigger_kind}</small></header><p>真实平台修改：否 · Plan #{execution.optimization_run_id}</p><ul>{execution.result_actions.map((action) => <li key={action.platform}><strong>{action.platform}</strong>：结果预算 {action.recommended_budget.toFixed(2)} · 竞价 {signedPercent(action.bid_adjustment_pct)}</li>)}</ul>{execution.status === "SUCCEEDED" && <button type="button" disabled={busy} onClick={rollback}>按精确Execution ID回滚</button>}</article>;
}

function signedPercent(value: number) {
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}
