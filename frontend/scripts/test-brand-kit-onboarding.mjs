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
    "/src/components/product/brandKitOnboardingState.ts",
  );
  const readiness = {
    backend: { ready: true, message: "ready" },
    qwen: { ready: false, message: "missing" },
    wanx: { ready: false, message: "missing" },
    google_youtube: { ready: false, message: "missing" },
    database: {
      ready: true,
      message: "head",
      revision_status: "head",
      revision: "0003_brand_kit_versions",
    },
    artifact_storage: { ready: true, message: "ready" },
    provider_calls: 0,
    database_writes: 0,
    automatic_actions: false,
  };
  const versionOne = {
    id: 11,
    brand_kit_id: 7,
    version_number: 1,
    digest: "a".repeat(64),
    brand_name: "North Star",
    positioning: "Practical",
    default_language: "English",
    brand_tone: "Clear",
    preferred_terms: ["trusted"],
    forbidden_terms: ["guaranteed"],
    target_regions: ["US"],
    audience_guidelines: [],
    visual_guidelines: [],
    required_disclosures: [],
    claims_constraints: [],
    created_at: "2026-08-09T00:00:00Z",
  };
  const kit = {
    id: 7,
    name: "North Star",
    created_at: versionOne.created_at,
    updated_at: versionOne.created_at,
    versions: [versionOne],
  };
  const product = {
    id: 3,
    brand_kit_version_id: null,
    name: "Product",
    category: "Category",
    description: "Description",
    selling_points: ["Point"],
    target_markets: ["US"],
    created_at: versionOne.created_at,
    updated_at: versionOne.created_at,
    assets: [],
  };
  const brief = { id: 5, product_id: 3 };

  assert.deepEqual(
    state
      .deriveOnboardingSteps(readiness, [], [], null, [])
      .map((step) => step.complete),
    [true, false, false, false, false, false],
  );
  assert.deepEqual(
    state
      .deriveOnboardingSteps(readiness, [kit], [], null, [])
      .map((step) => step.complete),
    [true, true, false, false, false, false],
  );
  assert.deepEqual(
    state
      .deriveOnboardingSteps(
        { ...readiness, qwen: { ready: true, message: "ready" } },
        [kit],
        [{ ...product, brand_kit_version_id: 11 }],
        { ...product, brand_kit_version_id: 11 },
        [brief],
      )
      .map((step) => step.complete),
    [true, true, true, true, true, true],
  );
  assert.equal(state.automaticallySelectedVersionId(kit), 11);
  assert.equal(
    state.automaticallySelectedVersionId({
      ...kit,
      versions: [versionOne, { ...versionOne, id: 12, version_number: 2 }],
    }),
    null,
  );
  assert.equal(state.findBrandKitVersion([kit], 11).id, 11);
  assert.equal(state.findBrandKitVersion([kit], 99), null);
  const versionTwo = { ...versionOne, id: 12, version_number: 2, digest: "b".repeat(64) };
  const withVersionTwo = state.mergeBrandKitVersion([kit], kit.id, versionTwo);
  assert.deepEqual(withVersionTwo[0].versions.map((version) => version.id), [11, 12]);
  assert.equal(state.mergeBrandKitVersion(withVersionTwo, kit.id, versionTwo)[0].versions.length, 2);
  assert.match(
    state.versionCreationMessage({ version: versionOne, reused: true }),
    /已复用版本 1/,
  );
  assert.match(state.SAFE_QWEN_CONFIGURATION_GUIDANCE, /QWEN_API_KEY/);
  assert.doesNotMatch(
    state.SAFE_QWEN_CONFIGURATION_GUIDANCE,
    /sk-|secret\s*=|token\s*=|api[_-]?key\s*=/i,
  );
  const requestLock = { current: false };
  let releaseRequest;
  let postCount = 0;
  const pendingRequest = new Promise((resolve) => {
    releaseRequest = resolve;
  });
  const action = async () => {
    postCount += 1;
    await pendingRequest;
    return "created";
  };
  const firstClick = state.runWithSynchronousRequestLock(requestLock, action);
  const secondClick = state.runWithSynchronousRequestLock(requestLock, action);
  assert.equal(postCount, 1);
  assert.equal(await secondClick, undefined);
  releaseRequest();
  assert.equal(await firstClick, "created");
  assert.equal(requestLock.current, false);

  const panel = read(
    "src",
    "components",
    "product",
    "BrandKitOnboardingPanel.tsx",
  );
  const page = read("src", "pages", "ProductCenterPage.tsx");
  const api = read("src", "api", "brandKits.ts");
  const marketing = read(
    "src",
    "components",
    "product",
    "MarketingTaskConfig.tsx",
  );

  assert.match(panel, /getSystemReadiness/);
  assert.match(panel, /listBrandKits/);
  assert.match(panel, /listMarketingTasks/);
  assert.match(
    panel,
    /\.catch\([\s\S]*setReadiness\(null\);[\s\S]*setBrandKits\(\[\]\);[\s\S]*setBriefs\(\[\]\);/,
  );
  assert.match(panel, /runWithSynchronousRequestLock\(createKitLock/);
  assert.match(panel, /runWithSynchronousRequestLock\(createVersionLock/);
  assert.match(panel, /runWithSynchronousRequestLock\(bindingLock/);
  assert.match(panel, /versionCreationMessage\(result\)/);
  assert.match(panel, /不会自动选择最新记录/);
  assert.match(panel, /selectedVersionId === null/);
  assert.match(panel, /解除绑定/);
  assert.match(panel, /preferred_terms/);
  assert.match(panel, /forbidden_terms/);
  assert.match(panel, /required_disclosures/);
  assert.match(panel, /claims_constraints/);
  assert.match(page, /!isPresentation && \(/);
  assert.match(page, /<BrandKitOnboardingPanel/);
  assert.match(page, /socialpilot\.productCenter\.selectedProduct/);
  assert.match(page, /restoredProductCenterSelection/);
  assert.match(marketing, /onTaskChanged\?\.\(task\)/);
  assert.match(api, /apiClient\.post<BrandKit>/);
  assert.match(api, /apiClient\.post<BrandKitVersionCreateResult>/);
  assert.match(api, /apiClient\.put<Product>/);
  assert.match(api, /apiClient\.delete<Product>/);
  assert.doesNotMatch(api, /preflight|provider|qwen|wanx|youtube|google/i);
  assert.doesNotMatch(panel, /localStorage|sessionStorage/);

  console.log(
    "BrandKit onboarding checks passed: persisted state derivation, exact versions, locks, safe configuration, Presentation isolation",
  );
} finally {
  await server.close();
}
