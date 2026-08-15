import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const scriptPath = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(scriptPath), "..");
const stateFile = path.join(
  root,
  "src/components/video/videoCompositionEnhancementState.ts",
);
const out = path.join(root, ".composition-enhancement-test-temp");

if (path.dirname(out) !== root) throw new Error("Unsafe test output directory");

let behaviorScenarios = 0;
let staticAssertions = 0;

const job = (status, overrides = {}) => ({
  id: 9,
  status,
  result_entity_type: null,
  result_entity_id: null,
  ...overrides,
});

try {
  const buildResult = await build({
    configFile: false,
    logLevel: "silent",
    build: {
      write: true,
      outDir: out,
      emptyOutDir: true,
      lib: { entry: stateFile, formats: ["es"], fileName: "state" },
      rollupOptions: { output: { entryFileNames: "state.mjs" } },
    },
  });
  const outputs = Array.isArray(buildResult) ? buildResult : [buildResult];
  const entries = outputs.flatMap((result) =>
    result.output.filter((item) => item.type === "chunk" && item.isEntry),
  );
  assert.deepEqual(entries.map((item) => item.fileName), ["state.mjs"]);
  const stateOutput = path.join(out, "state.mjs");
  const info = await fs.lstat(stateOutput);
  assert.ok(info.isFile() && !info.isSymbolicLink());
  const state = await import(`${pathToFileURL(stateOutput).href}?v=${Date.now()}`);

  const first = { id: 1, controller: new AbortController() };
  const second = { id: 2, controller: new AbortController() };
  const slot = { current: null };
  assert.equal(state.beginEnhancementOperation(slot, first), true);
  assert.equal(state.beginEnhancementOperation(slot, second), false);
  behaviorScenarios += 1; // rapid double click admits one operation
  assert.equal(state.finishEnhancementOperation(slot, second), false);
  assert.equal(slot.current, first);
  behaviorScenarios += 1; // stale finally cannot release replacement lock
  assert.equal(state.finishEnhancementOperation(slot, first), true);
  assert.equal(state.beginEnhancementOperation(slot, second), true);
  state.abortEnhancementOperation(slot);
  assert.equal(second.controller.signal.aborted, true);
  assert.equal(slot.current, null);
  behaviorScenarios += 1; // unmount/context change aborts and clears

  const identity = {
    productId: 1,
    compositionId: 2,
    artifactId: 3,
    jobId: 9,
    operationId: 4,
    controller: new AbortController(),
  };
  let current = identity;
  assert.equal(state.isCurrentEnhancementOperation(identity, current), true);
  for (const key of [
    "productId",
    "compositionId",
    "artifactId",
    "jobId",
    "operationId",
  ]) {
    current = { ...identity, [key]: identity[key] + 1 };
    assert.equal(state.isCurrentEnhancementOperation(identity, current), false);
    behaviorScenarios += 1;
  }
  current = { ...identity, controller: new AbortController() };
  assert.equal(state.isCurrentEnhancementOperation(identity, current), false);
  behaviorScenarios += 1;
  current = identity;

  let reads = 0;
  let concurrentReads = 0;
  let maxConcurrentReads = 0;
  let updates = [];
  let failures = 0;
  const sequence = [
    new Error("temporary"),
    job("QUEUED"),
    job("RUNNING"),
    job("SUCCEEDED", {
      result_entity_type: "video_composition_enhancement_artifact",
      result_entity_id: 17,
    }),
  ];
  await state.pollExactEnhancementJob({
    identity,
    current: () => current,
    delay: async () => {},
    read: async () => {
      reads += 1;
      concurrentReads += 1;
      maxConcurrentReads = Math.max(maxConcurrentReads, concurrentReads);
      const value = sequence.shift();
      concurrentReads -= 1;
      if (value instanceof Error) throw value;
      return value;
    },
    update: (value) => updates.push(value.status),
    temporaryFailure: () => {
      failures += 1;
    },
  });
  assert.equal(reads, 4);
  assert.equal(failures, 1);
  assert.deepEqual(updates, ["QUEUED", "RUNNING", "SUCCEEDED"]);
  assert.equal(maxConcurrentReads, 1);
  behaviorScenarios += 2; // same exact job survives temporary failure; serial GET

  let abortReads = 0;
  const waitingIdentity = { ...identity, controller: new AbortController() };
  current = waitingIdentity;
  await state.pollExactEnhancementJob({
    identity: waitingIdentity,
    current: () => current,
    delay: async (_ms, signal) => {
      waitingIdentity.controller.abort();
      assert.equal(signal.aborted, true);
    },
    read: async () => {
      abortReads += 1;
      return job("SUCCEEDED");
    },
    update: () => assert.fail("aborted timer updated state"),
    temporaryFailure: () => assert.fail("aborted timer reported failure"),
  });
  assert.equal(abortReads, 0);
  behaviorScenarios += 1;

  let postReadUpdates = 0;
  const inFlightIdentity = { ...identity, controller: new AbortController() };
  current = inFlightIdentity;
  await state.pollExactEnhancementJob({
    identity: inFlightIdentity,
    current: () => current,
    delay: async () => {},
    read: async () => {
      inFlightIdentity.controller.abort();
      return job("SUCCEEDED");
    },
    update: () => {
      postReadUpdates += 1;
    },
    temporaryFailure: () => {},
  });
  assert.equal(postReadUpdates, 0);
  behaviorScenarios += 1;

  assert.equal(
    state.exactEnhancementResult(
      job("SUCCEEDED", {
        result_entity_type: "video_composition_enhancement_artifact",
        result_entity_id: 17,
      }),
    ),
    17,
  );
  assert.equal(
    state.exactEnhancementResult(
      job("SUCCEEDED", {
        result_entity_type: "video_composition_artifact",
        result_entity_id: 17,
      }),
    ),
    null,
  );
  behaviorScenarios += 1;

  const panel = await fs.readFile(
    path.join(root, "src/components/video/VideoCompositionEnhancementPanel.tsx"),
    "utf8",
  );
  for (const expected of [
    "Stage 3A Artifact",
    "确定性静音 AAC 占位音轨",
    "真实配音",
    "Provider-free 增强 Preflight",
    "isPresentation",
    "beginEnhancementOperation",
    "finishEnhancementOperation",
  ]) {
    assert.ok(panel.includes(expected));
    staticAssertions += 1;
  }
  for (const forbidden of ["latest", "access_token", "refresh_token", "provider body"]) {
    assert.ok(!panel.toLowerCase().includes(forbidden));
    staticAssertions += 1;
  }

  console.log(
    `Video Composition Enhancement: ${behaviorScenarios} production behavior scenarios, ` +
      `${staticAssertions} static/safety assertions passed`,
  );
} finally {
  if (path.dirname(out) !== root) throw new Error("Unsafe test output directory");
  await fs.rm(out, { recursive: true, force: true });
}
