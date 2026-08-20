import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createServer } from "vite";

const root = process.cwd();
const read = (...parts) => readFileSync(join(root, ...parts), "utf8");
const server = await createServer({ appType: "custom", logLevel: "silent", root, server: { middlewareMode: true } });

try {
  const state = await server.ssrLoadModule("/src/components/growth/growthOptimizationState.ts");
  const digest = "a".repeat(64);
  const analysis = { product_id: 1, source_context_digest: digest, recommendation_digest: "b".repeat(64) };
  const context = { product_id: 1, context_digest: digest, context_ready: true };
  const policy = { total_budget: 300, target_roas: 2, minimum_platform_share: 0.05, performance_tilt_share: 0.15, maximum_bid_adjustment_pct: 0.2 };
  assert.equal(state.analysisMatchesContext(analysis, context), true);
  assert.equal(state.analysisMatchesContext({ ...analysis, product_id: 2 }, context), false);
  assert.equal(state.analysisMatchesContext({ ...analysis, source_context_digest: "c".repeat(64) }, context), false);
  assert.equal(state.canCreateOptimizationRun(analysis, context, policy, false), true);
  assert.equal(state.canCreateOptimizationRun(analysis, context, policy, true), false);
  assert.equal(state.canCreateOptimizationRun(null, context, policy, false), false);
  assert.equal(state.optimizationIdempotencyKey(analysis, policy), state.optimizationIdempotencyKey(analysis, policy));
  assert.notEqual(state.optimizationIdempotencyKey(analysis, policy), state.optimizationIdempotencyKey(analysis, { ...policy, total_budget: 301 }));
  const run = (id, status) => ({ id, status });
  assert.deepEqual(state.mergeOptimizationRun([run(2, "PROPOSED"), run(1, "SUPERSEDED")], run(2, "ACTIVE")).map((item) => [item.id, item.status]), [[1, "SUPERSEDED"], [2, "ACTIVE"]]);
  assert.equal(state.activeOptimizationRun([run(1, "SUPERSEDED"), run(2, "ACTIVE")]).id, 2);

  const panel = read("src", "components", "growth", "GrowthOptimizationPanel.tsx");
  const parent = read("src", "components", "GrowthCopilotPanel.tsx");
  const api = read("src", "api", "growth.ts");
  assert.match(panel, /setTimeout/);
  assert.doesNotMatch(panel, /setInterval/);
  assert.match(panel, /外部广告账户尚未连接/);
  assert.match(panel, /按精确Plan ID激活/);
  assert.match(parent, /preserveRecommendationIfUnchanged/);
  assert.match(parent, /contextDigestRef\.current !== result\.context_digest/);
  for (const endpoint of ["growth-optimization/plans", "activate"]) assert.match(api, new RegExp(endpoint));
  assert.doesNotMatch(panel, /access_token|client_secret|Bearer/i);
  console.log("growth optimization: 10 behavior scenarios, 8 static/safety assertions passed");
} finally {
  await server.close();
}
