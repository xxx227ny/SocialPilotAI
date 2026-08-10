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
    "/src/components/product/copyQueueState.ts",
  );
  const digest = "a".repeat(64);
  const base = {
    id: 8,
    job_type: "qwen.copy_matrix.generate.v1",
    source_type: "marketing_strategy",
    source_id: 4,
    input_digest: digest,
    input_payload: {
      product_id: 1,
      marketing_brief_id: 3,
      marketing_strategy_id: 4,
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

  assert.equal(state.selectExactCopyJob([base], 3, 1, 4, digest)?.id, 8);
  assert.equal(state.selectExactCopyJob([base], 2, 1, 4, digest), null);
  assert.equal(state.selectExactCopyJob([base], 3, 2, 4, digest), null);
  assert.equal(state.selectExactCopyJob([base], 3, 1, 5, digest), null);
  assert.equal(state.copyJobNeedsPolling(base), true);
  assert.equal(state.copyJobNeedsPolling({ ...base, status: "RUNNING" }), true);
  assert.equal(state.copyJobNeedsPolling({ ...base, status: "FAILED" }), false);
  assert.equal(
    state.copyJobAllowsExplicitRetry({ ...base, status: "FAILED", attempt_count: 1 }),
    true,
  );
  assert.equal(
    state.copyJobAllowsExplicitRetry({ ...base, status: "SUBMIT_UNKNOWN", uncertain: true }),
    false,
  );
  assert.equal(
    state.exactCopyResultId({
      ...base,
      status: "SUCCEEDED",
      result_entity_type: "copy_matrix",
      result_entity_id: 9,
    }),
    9,
  );

  const component = read("src", "components", "product", "CopyPreflightPanel.tsx");
  assert.match(component, /enqueueCopyJob/);
  assert.match(component, /listCopyJobs/);
  assert.match(component, /getCopyExecutionJob/);
  assert.match(component, /getExactCopyMatrix/);
  assert.match(component, /retryCopyExecutionJob/);
  assert.match(component, /submitLockRef\.current/);
  assert.match(component, /SUBMIT_UNKNOWN/);
  assert.doesNotMatch(component, /generateTaskBoundCopyMatrix/);
  assert.doesNotMatch(component, /getLatestCopyForStrategy/);

  const api = read("src", "api", "copies.ts");
  assert.match(api, /\/copy-jobs/);
  assert.match(api, /\/execution-jobs\/\$\{jobId\}/);
  assert.match(api, /\/copies\/\$\{copyMatrixId\}/);

  console.log("Copy queue frontend checks passed: 20 scenarios");
} finally {
  await server.close();
}
