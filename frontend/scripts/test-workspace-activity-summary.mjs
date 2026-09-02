import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("../src/api/dashboard.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../src/pages/DashboardPage.tsx", import.meta.url), "utf8");
const types = readFileSync(new URL("../src/types/dashboard.ts", import.meta.url), "utf8");

assert.match(api, /\/dashboard\/workspace-summary/);
assert.match(types, /data_scope: "current_workspace"/);
assert.match(types, /ai_calls: 0/);
assert.match(page, /当前工作区真实进度/);
assert.match(page, /只统计当前账号工作区已经保存的记录/);
assert.match(page, /读取时不会调用模型，也不会产生费用/);
assert.match(page, /summary\.product_count/);
assert.match(page, /summary\.copy_matrix_count/);
assert.match(page, /summary\.video_artifact_count/);
assert.doesNotMatch(page, /getDashScopeCredential/);
assert.doesNotMatch(page, /listProducts/);

console.log("Workspace activity summary checks passed: scoped, factual, and zero-call.");
