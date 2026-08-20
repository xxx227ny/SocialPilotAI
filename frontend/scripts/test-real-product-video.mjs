import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, ".real-product-video-test-temp");
let behavior = 0;
let safety = 0;
try {
  await build({
    configFile: false,
    logLevel: "silent",
    build: {
      write: true,
      outDir: output,
      emptyOutDir: true,
      lib: {
        entry: {
          state: path.join(root, "src/components/video/realProductVideoState.ts"),
          features: path.join(root, "src/config/features.ts"),
        },
        formats: ["es"],
      },
      rollupOptions: { output: { entryFileNames: "[name].mjs" } },
    },
  });
  const state = await import(
    `${pathToFileURL(path.join(output, "state.mjs")).href}?v=${Date.now()}`
  );
  const features = await import(
    `${pathToFileURL(path.join(output, "features.mjs")).href}?v=${Date.now()}`
  );
  const operation = new state.RealProductVideoOperation();
  const first = operation.begin();
  const second = operation.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(operation.current(first.id), false);
  assert.equal(operation.current(second.id), true);
  behavior++;
  const job = {
    id: 7,
    status: "SUCCEEDED",
    result_entity_type: "video_render_artifact",
    result_entity_id: 9,
  };
  assert.equal(state.requireSuccessfulResult(job, "video_render_artifact"), 9);
  behavior++;
  assert.throws(
    () =>
      state.requireSuccessfulResult(
        {
          ...job,
          status: "FAILED",
          safe_error_code: "VOICEOVER_EXCEEDS_TIMELINE",
        },
        "video_render_artifact",
      ),
    /旁白超过视频时间，请缩短文案/,
  );
  behavior++;
  await assert.rejects(() =>
    state.pollExactJob(
      { ...job, status: "FAILED", safe_error_code: "FAILED" },
      async () => assert.fail("terminal Job must not be re-read"),
      new AbortController().signal,
    ).then((value) => state.requireSuccessfulResult(value, "video_render_artifact")),
  );
  behavior++;
  assert.equal(features.realProductVideoEnabled, false);
  behavior++;
  const threePlatforms = state.selectThreePlatformSources([
    { variant_id: 4, platform: "instagram" },
    { variant_id: 2, platform: "youtube" },
    { variant_id: 1, platform: "tiktok" },
    { variant_id: 3, platform: "tiktok" },
  ]);
  assert.deepEqual(
    threePlatforms.map((source) => source.variant_id),
    [1, 2, 4],
  );
  behavior++;

  const panel = await fs.readFile(
    path.join(root, "src/components/video/RealProductVideoPanel.tsx"),
    "utf8",
  );
  const page = await fs.readFile(path.join(root, "src/pages/ProductCenterPage.tsx"), "utf8");
  const feature = await fs.readFile(path.join(root, "src/config/features.ts"), "utf8");
  for (const required of [
    "realProductVideoEnabled || isPresentation",
    "submitWanxProductImageJob",
    "preflightHappyHorseVideo",
    "submitHappyHorseVideo",
    "refreshHappyHorseVideo",
    "getProductImageAsset",
    "prepareProductVideo",
    "submitProductImageJob",
    "preflightVideoComposition",
    "submitVoiceoverJob",
    "preflightCompositionEnhancement",
    "longanhuan_v3.6",
    "千问云配音",
    "万象商品视觉",
    "HappyHorse参考图生视频",
    "生成单平台完整云成片",
    "下载HappyHorse MP4",
    "批量生成三平台完整成片",
    "selectThreePlatformSources",
    "三平台批量将按顺序执行",
    "旁白若超过15秒会安全停止",
    "下载MP4",
    "下载WebVTT",
  ]) {
    assert.ok(panel.includes(required));
    safety++;
  }
  assert.ok(page.includes("<RealProductVideoPanel product={product}"));
  assert.ok(feature.includes("VITE_ENABLE_REAL_PRODUCT_VIDEO"));
  assert.ok(!panel.toLowerCase().includes("latest"));
  assert.ok(!panel.includes("uploadProductImage"));
  safety += 4;
  console.log(
    `Real Product Video: ${behavior} product-state behavior scenarios, ${safety} static/safety assertions passed`,
  );
} finally {
  await fs.rm(output, { recursive: true, force: true });
}
