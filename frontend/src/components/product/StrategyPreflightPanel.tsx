import { useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import { getStrategyPreflight } from "../../api/strategies";
import type { MarketingTask } from "../../types/marketing";
import type { Product } from "../../types/product";
import type { StrategyPreflight } from "../../types/strategy";

type PreflightState = "idle" | "checking" | "passed" | "blocked" | "error";

const REQUIREMENT_LABELS: Record<string, string> = {
  product_name: "商品名称",
  product_category: "商品分类",
  product_description: "商品描述",
  product_selling_points: "商品卖点",
  target_market_snapshot: "目标市场快照",
  supported_platforms: "受支持的平台",
  audience: "受众（任务默认配置）",
  language: "语言（任务默认配置）",
  tone: "语气（任务默认配置）",
  objective: "目标（任务默认配置）",
  qwen_provider_type: "Qwen Provider 可用性",
  provider_configuration: "Provider 配置",
};

interface StrategyPreflightPanelProps {
  task: MarketingTask;
  product: Product;
}

export function StrategyPreflightPanel({
  task,
  product,
}: StrategyPreflightPanelProps) {
  const [state, setState] = useState<PreflightState>("idle");
  const [result, setResult] = useState<StrategyPreflight | null>(null);
  const [error, setError] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const requestLockRef = useRef(false);
  const activeContextRef = useRef({ taskId: task.id, productId: product.id });
  activeContextRef.current = { taskId: task.id, productId: product.id };

  useEffect(() => {
    requestIdRef.current += 1;
    requestLockRef.current = false;
    controllerRef.current?.abort();
    setState("idle");
    setResult(null);
    setError("");
    setAcknowledged(false);
    return () => controllerRef.current?.abort();
  }, [task.id, product.id]);

  async function runPreflight() {
    if (requestLockRef.current) return;

    const taskId = task.id;
    const productId = product.id;
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    requestLockRef.current = true;
    setState("checking");
    setResult(null);
    setError("");

    try {
      const nextResult = await getStrategyPreflight(taskId, controller.signal);
      const active = activeContextRef.current;
      if (
        controller.signal.aborted ||
        requestId !== requestIdRef.current ||
        active.taskId !== taskId ||
        active.productId !== productId ||
        nextResult.task_id !== taskId ||
        nextResult.product_id !== productId
      ) {
        return;
      }
      setResult(nextResult);
      setState(nextResult.ready ? "passed" : "blocked");
    } catch (caught) {
      if (controller.signal.aborted || requestId !== requestIdRef.current) return;
      setError(
        getApiErrorMessage(
          caught,
          "生成前检查失败。请确认 Backend 可用后重试；本次未调用 AI。",
        ),
      );
      setState("error");
    } finally {
      if (requestId === requestIdRef.current) requestLockRef.current = false;
    }
  }

  const eligibleForNextStage = Boolean(result?.ready && acknowledged);

  return (
    <section className="strategy-preflight" aria-label="营销策略生成前检查">
      <header className="strategy-preflight__header">
        <div>
          <span>STRATEGY PREFLIGHT · V2-C2.1A</span>
          <h5>营销策略生成前检查</h5>
          <p>只读取并核对已保存输入；不会调用 Qwen、不会生成或保存策略。</p>
        </div>
        <strong className={`strategy-preflight__status strategy-preflight__status--${state}`}>
          {state === "idle" && "等待检查"}
          {state === "checking" && "检查中"}
          {state === "passed" && "检查通过"}
          {state === "blocked" && "条件不足"}
          {state === "error" && "检查失败"}
        </strong>
      </header>

      <div className="strategy-preflight__boundary">
        本阶段 0 AI Calls。检查接口不解析 Provider 依赖，也不创建 MarketingStrategy、
        CopyMatrix、VideoProject、RenderTask 或 Artifact。
      </div>

      <dl className="strategy-preflight__context">
        <div><dt>任务</dt><dd>MarketingBrief #{task.id}</dd></div>
        <div><dt>商品</dt><dd>#{product.id} · {product.name}</dd></div>
        <div><dt>目标市场快照</dt><dd>{task.target_markets.join("、") || "未保存"}</dd></div>
        <div><dt>平台</dt><dd>{task.platforms.join("、") || "未保存"}</dd></div>
        <div><dt>受众（任务默认配置）</dt><dd>{task.audience}</dd></div>
        <div><dt>语言（任务默认配置）</dt><dd>{task.language}</dd></div>
        <div><dt>语气（任务默认配置）</dt><dd>{task.tone}</dd></div>
        <div><dt>目标（任务默认配置）</dt><dd>{task.objective}</dd></div>
      </dl>

      <button
        type="button"
        className="strategy-preflight__run"
        onClick={() => void runPreflight()}
        disabled={state === "checking"}
      >
        {state === "checking" ? "正在执行只读检查…" : state === "error" ? "重试生成前检查" : "运行生成前检查"}
      </button>

      {state === "error" && <p className="strategy-preflight__error" role="alert">{error}</p>}

      {result && (
        <div className="strategy-preflight__result" aria-live="polite">
          <dl>
            <div><dt>Provider</dt><dd>{result.provider_label}</dd></div>
            <div><dt>模型</dt><dd>{result.model_label}</dd></div>
            <div><dt>Provider 配置</dt><dd>{result.provider_configured ? "已检测到（不显示凭据）" : "未配置"}</dd></div>
            <div><dt>检查结论</dt><dd>{result.ready ? "输入与配置检查通过" : "尚未满足生成条件"}</dd></div>
          </dl>
          {!result.ready && (
            <div className="strategy-preflight__missing">
              <strong>待补充或修复</strong>
              <ul>
                {result.missing_requirements.map((requirement) => (
                  <li key={requirement}>{REQUIREMENT_LABELS[requirement] ?? requirement}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="strategy-preflight__cost">{result.cost_notice}</p>
        </div>
      )}

      <label className="strategy-preflight__acknowledgment">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        我理解真实生成会调用阿里云百炼 Qwen，并可能消耗比赛 Credits。
      </label>
      <p className="strategy-preflight__eligibility">
        {eligibleForNextStage
          ? "已满足下一阶段的授权前置条件；本阶段仍不会执行生成。"
          : "尚未满足下一阶段授权前置条件。确认仅保存在当前页面会话中。"}
      </p>
      <button type="button" className="strategy-preflight__execute" disabled>
        调用 Qwen 生成策略 · V2-C2.1B 经授权后开放
      </button>
    </section>
  );
}
