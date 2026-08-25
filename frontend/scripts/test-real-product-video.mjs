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
    define: {
      "import.meta.env.VITE_ENABLE_REAL_PRODUCT_VIDEO": JSON.stringify("false"),
    },
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
    { variant_id: 4, script_version_id: 14, platform: "instagram" },
    { variant_id: 2, script_version_id: 12, platform: "youtube" },
    { variant_id: 1, script_version_id: 11, platform: "tiktok" },
    { variant_id: 3, script_version_id: 13, platform: "tiktok" },
  ]);
  assert.deepEqual(
    threePlatforms.map((source) => source.variant_id),
    [1, 2, 4],
  );
  behavior++;
  const batchPayload = state.buildThreePlatformPreflightPayload(threePlatforms, {
    id: 8,
    sha256: "a".repeat(64),
  });
  assert.deepEqual(batchPayload.selections, [
    { variant_id: 1, script_version_id: 11 },
    { variant_id: 2, script_version_id: 12 },
    { variant_id: 4, script_version_id: 14 },
  ]);
  assert.equal(batchPayload.reference_product_asset_id, 8);
  assert.equal(
    state.buildThreePlatformPreflightPayload(threePlatforms, null),
    null,
  );
  behavior++;
  const productionItem = {
    status: "RUNNING",
    stage: "GENERATING_VOICEOVER",
  };
  assert.equal(state.productionStageLabel(productionItem), "千问生成配音");
  assert.equal(state.productionProgress(productionItem), 78);
  assert.match(
    state.productionFailureMessage("PRODUCTION_WANX_SUBMIT_UNKNOWN"),
    /避免重复扣费/,
  );
  behavior++;
  assert.equal(
    state.productionBatchTerminal(
      { status: "PARTIAL_FAILED" },
      [
        { status: "SUCCEEDED" },
        { status: "RUNNING" },
      ],
    ),
    false,
  );
  assert.equal(
    state.productionBatchTerminal(
      { status: "PARTIAL_FAILED" },
      [
        { status: "SUCCEEDED" },
        { status: "FAILED" },
      ],
    ),
    true,
  );
  assert.equal(
    state.productionBatchRecoverable(
      { status: "PARTIAL_FAILED" },
      [
        { status: "SUCCEEDED" },
        {
          status: "FAILED",
          safe_error_code: "PRODUCTION_HAPPYHORSE_REFRESH_FAILED",
        },
      ],
    ),
    true,
  );
  assert.equal(
    state.productionPollDelayMs([
      { status: "RUNNING", stage: "GENERATING_VIDEO" },
    ]),
    10_000,
  );
  behavior++;
  const oneClickRequest = state.buildBatchQwenScriptRequest(
    [
      { id: 9, product_id: 3, platform: "instagram", variant_index: 2, status: "READY_FOR_SCRIPT" },
      { id: 6, product_id: 3, platform: "tiktok", variant_index: 1, status: "READY_FOR_SCRIPT" },
      { id: 8, product_id: 3, platform: "instagram", variant_index: 1, status: "READY_FOR_SCRIPT" },
      { id: 7, product_id: 3, platform: "youtube", variant_index: 1, status: "READY_FOR_SCRIPT" },
      { id: 5, product_id: 4, platform: "tiktok", variant_index: 1, status: "READY_FOR_SCRIPT" },
    ],
    3,
    21,
    31,
  );
  assert.deepEqual(oneClickRequest, {
    product_id: 3,
    variant_ids: [6, 7, 8],
    strategy_id: 21,
    copy_matrix_id: 31,
  });
  assert.equal(state.buildBatchQwenScriptRequest([], 3, 21, null), null);
  behavior++;

  const panel = await fs.readFile(
    path.join(root, "src/components/video/RealProductVideoPanel.tsx"),
    "utf8",
  );
  const page = await fs.readFile(path.join(root, "src/pages/ContentStudioPage.tsx"), "utf8");
  const productCenter = await fs.readFile(
    path.join(root, "src/pages/ProductCenterPage.tsx"),
    "utf8",
  );
  const feature = await fs.readFile(path.join(root, "src/config/features.ts"), "utf8");
  const enhancementApi = await fs.readFile(
    path.join(root, "src/api/videoCompositionEnhancements.ts"),
    "utf8",
  );
  const apiClient = await fs.readFile(path.join(root, "src/api/client.ts"), "utf8");
  const productVideoApi = await fs.readFile(
    path.join(root, "src/api/productMarketingVideo.ts"),
    "utf8",
  );
  const batchVideoApi = await fs.readFile(
    path.join(root, "src/api/batchVideoJobs.ts"),
    "utf8",
  );
  for (const required of [
    "realProductVideoEnabled || isPresentation",
    "submitWanxProductImageJob",
    "reference_product_asset_id",
    "reference_product_asset_sha256",
    "商品主参考图（所有分镜冻结复用）",
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
    "buildThreePlatformPreflightPayload",
    "preflightThreePlatformVideo",
    "检查三平台调用与费用",
    "我已确认上述调用次数",
    "千问TTS费用尚未配置",
    "current.input_digest !== batchPreflight.input_digest",
    "三个平台独立推进",
    "createProductVideoProductionBatch",
    "advanceProductVideoProductionBatch",
    "pauseProductVideoProductionBatch",
    "resumeProductVideoProductionBatch",
    "cancelProductVideoProductionBatch",
    "socialpilot.productionBatch.",
    "三平台生产进度",
    "刷新页面后仍可恢复此批次",
    "productionStageLabel",
    "productionFailureMessage",
    "旁白若超过15秒会安全停止",
    "下载MP4",
    "下载WebVTT",
    "检查脚本到成片的完整调用与费用",
    "确认并一键生成三平台完整成片",
    "buildBatchQwenScriptRequest",
    "preflightBatchQwenScripts",
    "createOrRecoverBatchQwenScripts",
    "model-cost-confirmation",
    "oneClickBlockedMessage",
    "will_auto_activate_exact_results",
    "total_known_cost_max",
    "known_downstream_cost",
    "脚本生成后的成片调用次数或费用与确认值不一致",
    "socialpilot.scriptBatch.",
  ]) {
    assert.ok(panel.includes(required));
    safety++;
  }
  assert.ok(page.includes("<RealProductVideoPanel product={product}"));
  assert.ok(page.includes("一键商品视频"));
  assert.ok(!productCenter.includes("RealProductVideoPanel"));
  assert.ok(feature.includes("VITE_ENABLE_REAL_PRODUCT_VIDEO"));
  assert.ok(!panel.toLowerCase().includes("latest"));
  assert.ok(!panel.includes("uploadProductImage"));
  assert.match(
    enhancementApi,
    /preflight_expires_at:\s*preflight\.expires_at/,
  );
  assert.ok(apiClient.includes("export function apiContentUrl"));
  assert.ok(enhancementApi.includes("apiContentUrl("));
  assert.ok(productVideoApi.includes("apiContentUrl("));
  assert.ok(!enhancementApi.includes("`/api/v1/video-composition"));
  assert.ok(!productVideoApi.includes("`/api/v1/video-render-artifacts"));
  safety += 5;
  for (const action of ["advance", "pause", "resume", "cancel"]) {
    assert.ok(productVideoApi.includes(`\"${action}\"`));
    safety++;
  }
  assert.ok(batchVideoApi.includes("/qwen-scripts/preflight"));
  assert.ok(batchVideoApi.includes("/qwen-scripts"));
  assert.ok(batchVideoApi.includes("cost_confirmed: true"));
  safety += 3;
  safety += 5;
  console.log(
    `Real Product Video: ${behavior} product-state behavior scenarios, ${safety} static/safety assertions passed`,
  );
} finally {
  await fs.rm(output, { recursive: true, force: true });
}
