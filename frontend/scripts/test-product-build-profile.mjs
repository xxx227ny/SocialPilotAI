import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { productSocialOverrides, socialFeatures } from "./product-social-features.mjs";

const profile = readFileSync(new URL("./build-product.mjs", import.meta.url), "utf8");

assert.match(profile, /startsWith\("VITE_"\)/);
assert.doesNotMatch(profile, /VITE_API_BASE_URL\s*:/);

for (const feature of [
  "STRATEGY_EXECUTION",
  "COPY_EXECUTION",
  "V2_COPY_EXECUTION",
  "VIDEO_PROJECT_EXECUTION",
  "V2_VIDEO_PROJECT_EXECUTION",
  "VIDEO_RENDER_EXECUTION",
  "VIDEO_COMPOSITION",
  "VIDEO_COMPOSITION_ENHANCEMENT",
  "BATCH_VIDEO_JOBS",
  "VIDEO_SCRIPT_VERSIONS",
  "QWEN_VIDEO_SCRIPT_GENERATION",
  "REAL_PRODUCT_VIDEO",
  "GROWTH_EXECUTION",
]) {
  assert.match(profile, new RegExp(`VITE_ENABLE_${feature}: "true"`));
}

for (const feature of [
  "LIVE_WANX_DEMO",
  "SOCIAL_ACCOUNT_BINDING",
  "INSTAGRAM_ACCOUNT_BINDING",
  "TIKTOK_ACCOUNT_BINDING",
  "PINTEREST_ACCOUNT_BINDING",
  "YOUTUBE_PUBLISHING",
  "INSTAGRAM_PUBLISHING",
  "TIKTOK_PUBLISHING",
]) {
  assert.match(profile, new RegExp(`VITE_ENABLE_${feature}: "false"`));
}

assert.deepEqual(productSocialOverrides(), {});
for (const name of socialFeatures) {
  assert.deepEqual(productSocialOverrides(name), { [`VITE_ENABLE_${name}`]: "true" });
}
assert.throws(() => productSocialOverrides("INVALID"));
assert.match(profile, /productSocialOverrides\(process.env.SOCIALPILOT_SOCIAL_FEATURES\)/);
console.log("Product build profile passed: social release flags explicit and validated.");
