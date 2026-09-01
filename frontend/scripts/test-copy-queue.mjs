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
    max_attempts: 1,
    result_entity_type: null,
    result_entity_id: null,
    safe_error_code: null,
    uncertain: false,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
    completed_at: null,
  };

  assert.equal(state.selectExactCopyJob([base], 3, 1, 4, digest)?.id, 8);
  assert.equal(
    state.selectExactCopyJob(
      [base, { ...base, id: 12, status: "SUCCEEDED" }],
      3,
      1,
      4,
      digest,
    )?.id,
    12,
  );
  assert.equal(state.selectExactCopyJob([base], 2, 1, 4, digest), null);
  assert.equal(state.selectExactCopyJob([base], 3, 2, 4, digest), null);
  assert.equal(state.selectExactCopyJob([base], 3, 1, 5, digest), null);
  assert.equal(state.copyJobNeedsPolling(base), true);
  assert.equal(state.copyJobNeedsPolling({ ...base, status: "RUNNING" }), true);
  assert.equal(state.copyJobNeedsPolling({ ...base, status: "FAILED" }), false);
  assert.equal(
    state.copyJobAllowsExplicitRetry({ ...base, status: "FAILED", attempt_count: 1 }),
    false,
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
  const matrix = {
    id: 17,
    product_id: 1,
    marketing_strategy_id: 4,
    created_at: "2026-08-25T00:00:00Z",
    copies: [
      {
        platform: "TikTok",
        hook: "Fresh anywhere",
        caption: "Blend and go",
        hashtags: ["#Portable", "#Fresh"],
        cta: "Try it today",
      },
      {
        platform: "Instagram",
        hook: "Color your routine",
        caption: "A fresh habit",
        hashtags: ["#Lifestyle"],
        cta: "Save this idea",
      },
    ],
  };
  assert.match(state.platformCopyText(matrix.copies[0]), /Fresh anywhere/);
  assert.match(state.copyMatrixText(matrix), /Instagram/);
  assert.match(state.copyMatrixCsv(matrix), /^\uFEFF"平台"/);
  assert.match(state.copyMatrixCsv(matrix), /"#Portable #Fresh"/);

  const component = read("src", "components", "product", "CopyPreflightPanel.tsx");
  const workspaceCache = await server.ssrLoadModule(
    "/src/components/product/copyWorkspaceCache.ts",
  );
  const taskConfig = read("src", "components", "product", "MarketingTaskConfig.tsx");
  const copyPage = read("src", "pages", "CopyMatrixPage.tsx");
  const copyTypes = read("src", "types", "copy.ts");
  assert.match(component, /enqueueCopyJob/);
  assert.match(component, /listCopyJobs/);
  assert.match(component, /getCopyExecutionJob/);
  assert.match(component, /getExactCopyMatrix/);
  assert.match(component, /Promise\.all/);
  assert.match(component, /getCopyWorkspaceSnapshot/);
  assert.match(component, /setCopyWorkspaceSnapshot/);
  assert.match(component, /retryCopyExecutionJob/);
  assert.match(component, /submitLockRef\.current/);
  assert.match(component, /SUBMIT_UNKNOWN/);
  assert.match(component, /preflight\.estimated_cost/);
  assert.match(component, /禁止（只允许一次模型提交）/);
  assert.match(component, /复制整套文案/);
  assert.match(component, /复制此平台/);
  assert.match(component, /导出 JSON/);
  assert.match(component, /socialpilot\.videoStrategy\./);
  assert.match(component, /socialpilot\.videoCopyMatrix\./);
  assert.match(component, /导出 CSV/);
  assert.match(component, /document\.body\.appendChild\(link\)/);
  assert.match(component, /window\.setTimeout\(\(\) => URL\.revokeObjectURL\(url\), 1_000\)/);
  assert.match(component, /已导出/);
  assert.match(component, /重新生成文案/);
  assert.match(component, /regeneration_key/);
  assert.match(component, /crypto\.randomUUID/);
  assert.match(component, /原文案矩阵仍完整保留/);
  assert.doesNotMatch(component, /generateTaskBoundCopyMatrix/);
  assert.doesNotMatch(component, /getLatestCopyForStrategy/);
  assert.match(taskConfig, /Pinterest/);
  assert.match(taskConfig, /selectedPlatforms\.length <= 4/);
  assert.match(taskConfig, /选择完整四平台矩阵/);
  assert.match(copyPage, /四平台文案矩阵/);
  assert.match(copyPage, /搜索发现/);
  assert.match(copyPage, /socialpilot\.copyMatrix\.selectedProduct/);
  assert.match(copyPage, /socialpilot\.copyMatrix\.platformDrafts/);
  assert.match(copyPage, /restoredPlatformDrafts/);
  assert.match(copyTypes, /"Pinterest"/);

  workspaceCache.clearCopyWorkspaceCache();
  workspaceCache.setLatestTaskSnapshot(1, { id: 7, product_id: 1 });
  assert.equal(workspaceCache.getLatestTaskSnapshot(1).value.id, 7);
  workspaceCache.clearCopyWorkspaceCache();
  assert.equal(workspaceCache.getLatestTaskSnapshot(1), undefined);

  const api = read("src", "api", "copies.ts");
  assert.match(api, /\/copy-jobs/);
  assert.match(api, /\/execution-jobs\/\$\{jobId\}/);
  assert.match(api, /\/copies\/\$\{copyMatrixId\}/);
  assert.match(api, /regeneration_key\?: string/);

  console.log("Copy queue frontend checks passed: 46 scenarios");
} finally {
  await server.close();
}
