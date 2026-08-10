import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createServer } from "vite";

const root = process.cwd();
const read = (...parts) => readFileSync(join(root, ...parts), "utf8");
const server = await createServer({
  appType: "custom",
  logLevel: "silent",
  root,
  server: { middlewareMode: true },
});

try {
  const state = await server.ssrLoadModule(
    "/src/components/product/strategyQueueState.ts",
  );
  const digest = "a".repeat(64);
  const base = {
    id: 7,
    job_type: "qwen.strategy.generate.v1",
    source_type: "marketing_brief",
    source_id: 3,
    input_digest: digest,
    input_payload: {
      product_id: 1,
      marketing_brief_id: 3,
      frozen_digest: digest,
    },
    status: "QUEUED",
    attempt_count: 0,
    max_attempts: 2,
    result_entity_type: null,
    result_entity_id: null,
    safe_error_code: null,
    uncertain: false,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
    completed_at: null,
  };

  assert.equal(state.selectExactStrategyJob([base], 3, 1, digest)?.id, 7);
  assert.equal(state.selectExactStrategyJob([base], 4, 1, digest), null);
  assert.equal(state.selectExactStrategyJob([base], 3, 2, digest), null);
  assert.equal(state.selectExactStrategyJob([base], 3, 1, "b".repeat(64)), null);
  assert.equal(
    state.selectExactStrategyJob(
      [{ ...base, input_payload: { ...base.input_payload, product_id: 2 } }],
      3,
      1,
      digest,
    ),
    null,
  );
  assert.equal(state.jobNeedsPolling(base), true);
  assert.equal(state.jobNeedsPolling({ ...base, status: "RUNNING" }), true);
  assert.equal(state.jobNeedsPolling({ ...base, status: "FAILED" }), false);
  assert.equal(
    state.jobAllowsExplicitRetry({
      ...base,
      status: "FAILED",
      attempt_count: 1,
    }),
    true,
  );
  assert.equal(
    state.jobAllowsExplicitRetry({
      ...base,
      status: "SUBMIT_UNKNOWN",
      uncertain: true,
    }),
    false,
  );
  assert.equal(
    state.jobAllowsExplicitRetry({
      ...base,
      status: "FAILED",
      attempt_count: 2,
    }),
    false,
  );
  assert.equal(
    state.exactStrategyResultId({
      ...base,
      status: "SUCCEEDED",
      result_entity_type: "marketing_strategy",
      result_entity_id: 9,
    }),
    9,
  );
  assert.equal(
    state.exactStrategyResultId({
      ...base,
      status: "SUCCEEDED",
      result_entity_type: "other",
      result_entity_id: 9,
    }),
    null,
  );

  const component = read(
    "src",
    "components",
    "product",
    "StrategyPreflightPanel.tsx",
  );
  assert.match(component, /enqueueStrategyJob/);
  assert.match(component, /listStrategyJobs/);
  assert.match(component, /getExecutionJob/);
  assert.match(component, /getExactMarketingStrategy/);
  assert.match(component, /retryExecutionJob/);
  assert.match(component, /submitLockRef\.current/);
  assert.match(component, /SUBMIT_UNKNOWN/);
  assert.doesNotMatch(component, /generateMarketingStrategy/);
  assert.doesNotMatch(component, /getLatestMarketingStrategy/);

  const api = read("src", "api", "strategies.ts");
  assert.match(api, /\/strategy-jobs/);
  assert.match(api, /\/execution-jobs\/\$\{jobId\}/);
  assert.match(api, /\/strategies\/\$\{strategyId\}/);

  const productCenter = read("src", "pages", "ProductCenterPage.tsx");
  assert.match(productCenter, /!isPresentation[\s\S]*MarketingTaskConfig/);

  console.log("Strategy queue frontend checks passed: 23 scenarios");
} finally {
  await server.close();
}
