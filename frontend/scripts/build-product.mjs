import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { productSocialOverrides } from "./product-social-features.mjs";

// A product release must be reproducible and must not inherit a developer's
// machine-specific VITE_* variables or .env.local feature switches.
const environment = { ...process.env };
for (const name of Object.keys(environment)) {
  if (name.startsWith("VITE_")) delete environment[name];
}

Object.assign(environment, {
  VITE_ENABLE_STRATEGY_EXECUTION: "true",
  VITE_ENABLE_COPY_EXECUTION: "true",
  VITE_ENABLE_V2_COPY_EXECUTION: "true",
  VITE_ENABLE_VIDEO_PROJECT_EXECUTION: "true",
  VITE_ENABLE_V2_VIDEO_PROJECT_EXECUTION: "true",
  VITE_ENABLE_VIDEO_RENDER_EXECUTION: "true",
  VITE_ENABLE_VIDEO_COMPOSITION: "true",
  VITE_ENABLE_VIDEO_COMPOSITION_ENHANCEMENT: "true",
  VITE_ENABLE_BATCH_VIDEO_JOBS: "true",
  VITE_ENABLE_VIDEO_SCRIPT_VERSIONS: "true",
  VITE_ENABLE_QWEN_VIDEO_SCRIPT_GENERATION: "true",
  VITE_ENABLE_REAL_PRODUCT_VIDEO: "true",
  VITE_ENABLE_GROWTH_EXECUTION: "true",
  VITE_ENABLE_LIVE_WANX_DEMO: "false",
  VITE_ENABLE_SOCIAL_ACCOUNT_BINDING: "false",
  VITE_ENABLE_INSTAGRAM_ACCOUNT_BINDING: "false",
  VITE_ENABLE_TIKTOK_ACCOUNT_BINDING: "false",
  VITE_ENABLE_PINTEREST_ACCOUNT_BINDING: "false",
  VITE_ENABLE_YOUTUBE_PUBLISHING: "false",
  VITE_ENABLE_INSTAGRAM_PUBLISHING: "false",
  VITE_ENABLE_TIKTOK_PUBLISHING: "false",
});
Object.assign(environment, productSocialOverrides(process.env.SOCIALPILOT_SOCIAL_FEATURES));

run(resolve("node_modules", "typescript", "bin", "tsc"), ["-b"]);
run(resolve("node_modules", "vite", "bin", "vite.js"), ["build", "--mode", "product"]);

function run(modulePath, arguments_) {
  const result = spawnSync(process.execPath, [modulePath, ...arguments_], {
    cwd: process.cwd(),
    env: environment,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
