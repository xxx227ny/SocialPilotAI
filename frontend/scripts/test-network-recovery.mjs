import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const main = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");
const worker = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
const productForm = readFileSync(
  new URL("../src/components/product/ProductCreateForm.tsx", import.meta.url),
  "utf8",
);

assert.match(main, /import\.meta\.env\.PROD/);
assert.match(main, /serviceWorker\.register\("\/sw\.js"/);
assert.match(worker, /request\.mode === "navigate"/);
assert.match(worker, /fetchWithTimeout\(request, 5_000\)/);
assert.match(worker, /caches\.match\(APP_SHELL\)/);
assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
assert.doesNotMatch(worker, /cache\.put\([^\n]*(?:api|auth|credential|media)/i);
assert.match(productForm, /isUnconfirmedApiMutation/);
assert.match(productForm, /await listProducts\(\)/);
assert.match(productForm, /matchesRecentCreation/);
assert.match(productForm, /Date\.parse\(product\.created_at\)/);
assert.match(productForm, /正在创建，请勿重复提交/);

const builtWorker = new URL("../dist/sw.js", import.meta.url);
if (existsSync(builtWorker)) {
  assert.match(readFileSync(builtWorker, "utf8"), /socialpilot-app-shell-v1/);
}

console.log("Network recovery frontend checks passed: 12 safety assertions.");
