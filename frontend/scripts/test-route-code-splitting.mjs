import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

for (const page of [
  "DashboardPage",
  "ProductCenterPage",
  "CopyMatrixPage",
  "ContentStudioPage",
  "GrowthCopilotPage",
  "SnapshotPresentationPage",
  "ApiKeySettingsPage",
  "SocialAccountsPage",
  "AccountSecurityPage",
]) {
  assert.match(app, new RegExp(`const ${page} = lazy\\(`));
  assert.doesNotMatch(app, new RegExp(`import \\{ ${page} \\} from`));
}
assert.match(app, /<Suspense fallback=\{<PageLoading \/>\}>/);
assert.match(app, /正在加载当前功能/);

console.log("Route code splitting checks passed: nine non-login pages load on demand.");
