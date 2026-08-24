import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const stateFile = path.join(root, "src/components/video/batchVideoJobState.ts");
const featuresFile = path.join(root, "src/config/features.ts");
const output = path.join(root, ".batch-video-test-temp");
if (path.dirname(output) !== root) throw new Error("Unsafe test output directory");

let behaviorScenarios = 0;
let staticAssertions = 0;

try {
  await build({
    configFile: false,
    logLevel: "silent",
    build: {
      write: true,
      outDir: output,
      emptyOutDir: true,
      lib: {
        entry: { state: stateFile, features: featuresFile },
        formats: ["es"],
      },
      rollupOptions: { output: { entryFileNames: "[name].mjs" } },
    },
  });
  const state = await import(
    `${pathToFileURL(path.join(output, "state.mjs")).href}?v=${Date.now()}`
  );
  const featureModule = await import(
    `${pathToFileURL(path.join(output, "features.mjs")).href}?v=${Date.now()}`
  );

  assert.equal(
    state.expandedVariantCount([3, 1, 2], ["youtube", "tiktok", "instagram"], 2),
    18,
  );
  behaviorScenarios += 1;

  const first = { id: 1, batchId: null, controller: new AbortController() };
  const second = { id: 2, batchId: null, controller: new AbortController() };
  const slot = { current: null };
  assert.equal(state.beginBatchOperation(slot, first), true);
  assert.equal(state.beginBatchOperation(slot, second), false);
  behaviorScenarios += 1;
  assert.equal(state.finishBatchOperation(slot, second), false);
  assert.equal(slot.current, first);
  assert.equal(state.finishBatchOperation(slot, first), true);
  behaviorScenarios += 1;

  const a = { id: 3, batchId: 10, controller: new AbortController() };
  const b = { id: 4, batchId: 11, controller: new AbortController() };
  slot.current = a;
  assert.equal(state.isCurrentBatchOperation(a, slot.current), true);
  slot.current = b;
  assert.equal(state.isCurrentBatchOperation(a, slot.current), false);
  behaviorScenarios += 1;

  let reads = 0;
  let updates = 0;
  slot.current = b;
  await state.refreshExactBatch({
    operation: b,
    current: () => slot.current,
    read: async (batchId) => {
      reads += 1;
      assert.equal(batchId, 11);
      return [{ id: 1, status: "WAITING" }];
    },
    update: () => {
      updates += 1;
    },
  });
  assert.equal(reads, 1);
  assert.equal(updates, 1);
  behaviorScenarios += 1;
  state.abortBatchOperation(slot);
  assert.equal(b.controller.signal.aborted, true);
  behaviorScenarios += 1;

  const request = {
    product_ids: [1, 2, 3],
    platforms: ["youtube", "tiktok", "instagram"],
    variants_per_platform: 2,
  };
  const batch = (status = "QUEUED", id = 41) => ({
    id,
    status,
    downstream_provider_cost_status: "NOT_ESTIMATED",
  });
  const calls = [];
  const fakeApi = {
    preflight: async () => {
      calls.push("preflight");
      return { current_stage_cost: "0" };
    },
    create: async () => {
      calls.push("create");
      return { batch: batch(), variants: [{ id: 1 }], reused: true };
    },
    readBatch: async (id) => {
      calls.push(`batch:${id}`);
      return batch("QUEUED", id);
    },
    readVariants: async (id) => {
      calls.push(`variants:${id}`);
      return [{ id: 1, batch_video_job_id: id }];
    },
    control: async (id, action) => {
      calls.push(`${action}:${id}`);
      return batch(action.toUpperCase(), id);
    },
  };
  const signal = new AbortController().signal;
  const created = await state.createBatchWorkflow(fakeApi, request, signal);
  assert.equal(created.reused, true);
  assert.deepEqual(calls.splice(0), ["preflight", "create"]);
  behaviorScenarios += 1;

  const recovered = await state.recoverExactBatchWorkflow(fakeApi, 41, signal);
  assert.equal(recovered.batch.id, 41);
  assert.equal(recovered.variants[0].batch_video_job_id, 41);
  assert.deepEqual(calls.splice(0), ["batch:41", "variants:41"]);
  behaviorScenarios += 1;

  for (const action of ["pause", "resume", "cancel"]) {
    const controlled = await state.controlBatchWorkflow(fakeApi, 41, action, signal);
    assert.equal(controlled.batch.id, 41);
    assert.deepEqual(calls.splice(0), [
      `${action}:41`,
      "batch:41",
      "variants:41",
    ]);
  }
  behaviorScenarios += 1;

  let activeReads = 0;
  let maximumReads = 0;
  let serialReads = 0;
  const pollUpdates = [];
  await state.pollBatchSerial({
    batchId: 41,
    signal,
    delay: async () => {},
    read: async (id) => {
      activeReads += 1;
      maximumReads = Math.max(maximumReads, activeReads);
      const statuses = ["QUEUED", "RUNNING", "READY_FOR_SCRIPT"];
      const snapshot = { batch: batch(statuses[serialReads], id), variants: [] };
      serialReads += 1;
      activeReads -= 1;
      return snapshot;
    },
    update: (snapshot) => pollUpdates.push(snapshot.batch.status),
    failure: () => assert.fail("serial poll must not fail"),
  });
  assert.equal(maximumReads, 1);
  assert.deepEqual(pollUpdates, ["QUEUED", "RUNNING", "READY_FOR_SCRIPT"]);
  behaviorScenarios += 1;

  let failedReads = 0;
  let pollFailures = 0;
  await state.pollBatchSerial({
    batchId: 41,
    signal,
    delay: async () => {},
    read: async () => {
      failedReads += 1;
      throw new Error("backend disconnected");
    },
    update: () => assert.fail("failed poll must not update"),
    failure: () => {
      pollFailures += 1;
    },
  });
  assert.equal(failedReads, 1);
  assert.equal(pollFailures, 1);
  behaviorScenarios += 1;

  assert.equal(state.downstreamCostLabel("NOT_ESTIMATED"), "尚未估算");
  assert.equal(state.downstreamCostLabel("UNKNOWN"), "成本状态不可用");
  behaviorScenarios += 1;

  assert.equal(featureModule.isEnabledFeatureFlag(undefined), false);
  assert.equal(featureModule.isEnabledFeatureFlag("false"), false);
  assert.equal(featureModule.isEnabledFeatureFlag("true"), true);
  behaviorScenarios += 1;

  let presentationRequests = 0;
  if (state.shouldMountBatchVideoFlow(true, true)) presentationRequests += 1;
  assert.equal(presentationRequests, 0);
  assert.equal(state.shouldMountBatchVideoFlow(false, false), false);
  assert.equal(state.shouldMountBatchVideoFlow(true, false), true);
  behaviorScenarios += 1;

  const panel = await fs.readFile(
    path.join(root, "src/components/video/BatchVideoJobPanel.tsx"),
    "utf8",
  );
  const page = await fs.readFile(
    path.join(root, "src/pages/ContentStudioPage.tsx"),
    "utf8",
  );
  const featureSource = await fs.readFile(
    path.join(root, "src/config/features.ts"),
    "utf8",
  );
  const batchApiSource = await fs.readFile(
    path.join(root, "src/api/batchVideoJobs.ts"),
    "utf8",
  );
  const batchStateSource = await fs.readFile(stateFile, "utf8");
  const scriptPanelSource = await fs.readFile(
    path.join(root, "src/components/video/VideoScriptVersionPanel.tsx"),
    "utf8",
  );
  for (const expected of [
    "orchestration_only",
    "downstreamCostLabel",
    "按精确Batch ID恢复",
    "createBatchWorkflow",
    "recoverExactBatchWorkflow",
    "controlBatchWorkflow",
    "pollBatchSerial",
    "Backend连接中断",
  ]) {
    assert.ok(panel.includes(expected));
    staticAssertions += 1;
  }
  assert.ok(page.includes("shouldMountBatchVideoFlow"));
  assert.ok(featureSource.includes("VITE_ENABLE_BATCH_VIDEO_JOBS"));
  assert.ok(!featureSource.includes("VITE_ENABLE_BATCH_VIDEO_JOBS ??"));
  staticAssertions += 3;
  for (const forbidden of ["latest", "pinterest", "wanx", "ffmpeg"]) {
    assert.ok(!panel.toLowerCase().includes(forbidden));
    staticAssertions += 1;
  }
  assert.ok(batchApiSource.includes("preflightBatchQwenScripts"));
  assert.ok(batchApiSource.includes("createOrRecoverBatchQwenScripts"));
  assert.ok(batchApiSource.includes("/qwen-scripts/preflight"));
  assert.ok(batchApiSource.includes("/qwen-scripts"));
  assert.ok(!batchStateSource.toLowerCase().includes("qwen"));
  assert.ok(panel.includes("qwenEnabled={qwenScriptEnabled}"));
  assert.ok(
    panel.includes(
      "scriptVariantId !== null && <VideoScriptVersionPanel",
    ),
  );
  assert.ok(
    featureSource.includes(
      "qwenVideoScriptGenerationEnabled = isEnabledFeatureFlag",
    ),
  );
  assert.ok(
    featureSource.includes("VITE_ENABLE_QWEN_VIDEO_SCRIPT_GENERATION"),
  );
  assert.ok(
    page.includes(
      "showBatchVideoJobs && <BatchVideoJobPanel",
    ),
  );
  assert.ok(
    page.includes(
      "qwenScriptEnabled={qwenVideoScriptGenerationEnabled}",
    ),
  );
  assert.ok(!panel.includes("preflightQwenVideoScript"));
  assert.ok(!panel.includes("createQwenVideoScriptJob"));
  assert.ok(!/Promise\.all\s*\(\s*result\.variants/i.test(panel));
  assert.ok(scriptPanelSource.includes("qwenApi.preflight(variant.id"));
  assert.ok(
    scriptPanelSource.includes(
      "confirmAndCreateQwenJob(qwenApi,variant.id",
    ),
  );
  staticAssertions += 13;

  let presentationQwenRequests = 0;
  if (state.shouldMountBatchVideoFlow(true, true)) {
    presentationQwenRequests += 1;
  }
  assert.equal(presentationQwenRequests, 0);
  behaviorScenarios += 1;

  console.log(
    `Batch Video Job: ${behaviorScenarios} production state behavior scenarios, ` +
      `${staticAssertions} static/safety assertions passed`,
  );
} finally {
  await fs.rm(output, { recursive: true, force: true });
}
