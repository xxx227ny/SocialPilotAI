import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createServer } from "vite";

const root = process.cwd();
const server = await createServer({
  appType: "custom",
  logLevel: "silent",
  root,
  server: { middlewareMode: true },
});

try {
  const state = await server.ssrLoadModule(
    "/src/components/video/initialVideoProjectState.ts",
  );
  const source = {
    product_id: 1,
    strategy_id: 4,
    copy_matrix_id: 7,
    selected_by: "latest_valid_copy_matrix",
    provider_calls: 0,
    database_writes: 0,
  };
  assert.deepEqual(state.selectExactInitialVideoSource(1, source), {
    strategy_id: 4,
    copy_matrix_id: 7,
  });
  assert.equal(state.selectExactInitialVideoSource(2, source), null);
  assert.equal(
    state.selectExactInitialVideoSource(1, {
      ...source,
      copy_matrix_id: 0,
    }),
    null,
  );

  const request = {
    strategy_id: 4,
    copy_matrix_id: 7,
    platform: "TikTok",
    duration_seconds: 30,
    aspect_ratio: "9:16",
  };
  const preflight = {
    ...request,
    ready_for_execution: true,
    expires_at: "2099-01-01T00:00:00Z",
  };
  const executable = {
    frontendGateEnabled: true,
    preflight,
    request,
    costConfirmed: true,
    executionLocked: false,
    resultPresent: false,
    now: 0,
  };
  assert.equal(state.canExecuteInitialVideoProject(executable), true);
  for (const field of [
    "frontendGateEnabled",
    "costConfirmed",
  ]) {
    assert.equal(
      state.canExecuteInitialVideoProject({ ...executable, [field]: false }),
      false,
    );
  }
  assert.equal(
    state.canExecuteInitialVideoProject({
      ...executable,
      executionLocked: true,
    }),
    false,
  );
  assert.equal(
    state.canExecuteInitialVideoProject({
      ...executable,
      resultPresent: true,
    }),
    false,
  );
  assert.equal(
    state.canExecuteInitialVideoProject({
      ...executable,
      request: { ...request, copy_matrix_id: 8 },
    }),
    false,
  );
  assert.equal(
    state.canExecuteInitialVideoProject({
      ...executable,
      preflight: { ...preflight, expires_at: "2000-01-01T00:00:00Z" },
      now: Date.now(),
    }),
    false,
  );

  const component = readFileSync(
    join(root, "src", "components", "video", "InitialVideoProjectPanel.tsx"),
    "utf8",
  );
  assert.match(component, /执行Provider-free Preflight/);
  assert.match(component, /confirm_cost: true/);
  assert.match(component, /expected_preflight_digest: preflight\.preflight_digest/);
  assert.match(component, /preflight_expires_at: preflight\.expires_at/);
  assert.match(component, /executionLock\.current/);
  assert.match(component, /未自动重试，也未读取latest结果/);
  assert.doesNotMatch(component, /getLatestVideoProjectForProduct/);
  assert.doesNotMatch(component, /getLatestMarketingStrategy/);
  assert.doesNotMatch(component, /getLatestCopyForStrategy/);
  assert.match(component, /getInitialVideoProjectSource/);
  assert.match(component, /onGenerated\(generated\.generated_video_project\.id\)/);

  const api = readFileSync(join(root, "src", "api", "videos.ts"), "utf8");
  assert.match(api, /\/video-projects\/preflight/);
  assert.match(api, /\/video-projects\/execute/);
  assert.match(api, /\/video-projects\/source/);
  const features = readFileSync(
    join(root, "src", "config", "features.ts"),
    "utf8",
  );
  assert.match(features, /VITE_ENABLE_VIDEO_PROJECT_EXECUTION/);

  console.log("Initial VideoProject frontend checks passed: 19 scenarios");
} finally {
  await server.close();
}
