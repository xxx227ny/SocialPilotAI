import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("../src/api/dashboard.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../src/pages/DashboardPage.tsx", import.meta.url), "utf8");
const types = readFileSync(new URL("../src/types/dashboard.ts", import.meta.url), "utf8");

assert.match(api, /\/dashboard\/workspace-summary/);
assert.match(types, /data_scope: "current_workspace"/);
assert.match(types, /ai_calls: number/);
assert.match(types, /confirmed_estimated_costs:/);
assert.match(page, /当前工作区真实进度/);
assert.match(page, /只统计当前账号工作区已经保存的记录/);
assert.match(page, /读取时不会调用模型，也不会产生费用/);
assert.match(page, /summary\.product_count/);
assert.match(types, /product_asset_storage_bytes: number/);
assert.match(types, /product_asset_storage_limit_bytes: number/);
assert.match(page, /素材占用/);
assert.match(page, /formatStorage\(summary\.product_asset_storage_bytes\)/);
assert.match(page, /summary\.copy_matrix_count/);
assert.match(page, /summary\.video_artifact_count/);
assert.match(page, /summary\.ai_calls/);
assert.match(page, /预算估算，并非服务商账单/);
assert.match(types, /connected_social_account_count: number/);
assert.match(types, /successful_publish_count: number/);
assert.match(types, /publish_attention_count: number/);
assert.match(page, /summary\.connected_social_account_count/);
assert.match(page, /summary\.successful_publish_count/);
assert.match(page, /summary\.publish_attention_count/);
assert.doesNotMatch(page, /getDashScopeCredential/);
assert.doesNotMatch(page, /listProducts/);

console.log("Workspace activity summary checks passed: scoped, factual, and read-only.");
