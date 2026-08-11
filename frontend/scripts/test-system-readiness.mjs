import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const component = readFileSync(
  join(root, "src", "components", "system", "SystemReadinessPanel.tsx"),
  "utf8",
);
const layout = readFileSync(join(root, "src", "layouts", "AppLayout.tsx"), "utf8");
const api = readFileSync(join(root, "src", "api", "health.ts"), "utf8");
const types = readFileSync(join(root, "src", "types", "health.ts"), "utf8");

for (const label of [
  "Backend",
  "Qwen",
  "Wanx",
  "Google / YouTube",
  "Meta / Instagram",
  "Database",
  "Artifact Storage",
  "Execution Worker",
]) {
  assert.match(component, new RegExp(label.replace("/", "\\/")));
}
assert.match(component, /仅检查本机配置，不调用Provider/);
assert.match(component, /start-socialpilotai\.cmd/);
assert.match(component, /getSystemReadiness/);
assert.match(api, /\/system\/readiness/);
assert.match(layout, /!isPresentation && <SystemReadinessPanel/);
assert.doesNotMatch(types, /api_key|client_secret|access_token|refresh_token/i);
assert.match(types, /provider_calls: 0/);
assert.match(types, /meta_instagram: SystemReadinessItem/);
assert.match(types, /database_writes: 0/);
assert.match(types, /automatic_actions: false/);
assert.match(types, /revision_status: "head" \| "upgrade_required" \| "unavailable"/);
assert.match(types, /revision: string \| null/);
assert.match(component, /Revision:/);
assert.match(types, /status: "healthy" \| "not_running" \| "stale"/);
assert.doesNotMatch(types, /worker_pid|worker_path|lease_owner_digest/i);

console.log("System readiness frontend checks passed: safe labels, local guidance, Presentation isolation, no secret fields");
