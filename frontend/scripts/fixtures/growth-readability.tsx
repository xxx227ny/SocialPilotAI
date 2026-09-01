import React from "react";
import { createRoot } from "react-dom/client";
import { apiClient } from "../../src/api/client";
import { GrowthOptimizationPanel } from "../../src/components/growth/GrowthOptimizationPanel";
import type { FeedbackContext } from "../../src/types/growth";
import "../../src/styles.css";

// Deliberately isolated: no login, real API, model call, or database write.
const productId = 987001;
const digest = "a".repeat(64);
const actions = ["Facebook", "Instagram", "Pinterest", "TikTok"].map((platform, index) => ({
  platform, recommended_budget: [72.59, 92.99, 204.04, 130.38][index],
  bid_adjustment_pct: [-0.06, 0, 0.06, 0.11][index], action: ["decrease", "hold", "increase", "increase"][index],
}));
const run = { id: 1, product_id: productId, status: "ACTIVE", source_context_digest: digest,
  recommended_total_budget: 500, actions };
apiClient.defaults.adapter = async (config) => {
  if (config.method !== "get") throw new Error("Readability fixture prohibits all writes");
  let data: unknown;
  if (config.url?.endsWith("/plans")) data = [run];
  else if (config.url?.endsWith("/executions")) data = [
    { id: 1, status: "ROLLED_BACK", trigger_kind: "MANUAL_CONFIRMATION", optimization_run_id: 1, result_actions: actions },
    { id: 2, status: "SUCCEEDED", trigger_kind: "AUTO_POLICY", optimization_run_id: 1, result_actions: actions },
  ];
  else if (config.url?.endsWith("/cycles")) data = [{ id: 1, status: "EXECUTED", optimization_run_id: 1,
    execution_id: 2, resolution_status: "UNRESOLVED", context_digest: digest }];
  else if (config.url?.endsWith("/automation")) data = {
    product_id: productId, mode: "AUTO_SANDBOX", kill_switch_engaged: true, maximum_total_budget: 500,
    maximum_budget_change_pct: 0.5, maximum_bid_adjustment_pct: 0.2, monitoring_enabled: true,
    evaluation_interval_seconds: 900, execution_mode: "SANDBOX", external_mutation_allowed: false,
  };
  else throw new Error(`Unimplemented isolated read: ${config.url}`);
  return { data, status: 200, statusText: "OK", headers: {}, config };
};
const context = { product_id: productId, context_digest: digest, context_ready: true } as FeedbackContext;
createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 20 }}>
    <h1>投流文字隔离验收 · 模拟记录 · 不连接真实后台</h1>
    <div className="competition-page growth-workspace-page">
      <header className="competition-hero"><div><span>投流优化工作台</span><h1>AI 投流策略优化</h1></div></header>
      <section className="growth-panel">
        <div className="growth-panel__controls"><label><span>选择CSV文件</span><input type="file" /></label><button disabled>导入广告数据</button></div>
        <GrowthOptimizationPanel productId={productId} context={context} analysis={null}
          refreshContext={async () => {}} requestQwenReplan={() => {}} replanCycleId={null} replanResolved={() => {}} />
      </section>
    </div>
  </main>,
);
