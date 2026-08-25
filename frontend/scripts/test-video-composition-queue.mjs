import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const scriptPath = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(scriptPath), "..");
const stateFile = path.join(root, "src/components/video/videoCompositionState.ts");
const out = path.join(root, ".composition-test-temp");

if (path.dirname(out) !== root) {
  throw new Error("Unsafe test output directory");
}

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
  const buildOutputs = Array.isArray(buildResult) ? buildResult : [buildResult];
  const entryChunks = buildOutputs.flatMap((result) =>
    result.output.filter((item) => item.type === "chunk" && item.isEntry),
  );
  assert.deepEqual(entryChunks.map((item) => item.fileName), ["state.mjs"]);
  const stateOutput = path.join(out, "state.mjs");
  assert.equal(path.dirname(stateOutput), out);
  const stateOutputInfo = await fs.lstat(stateOutput);
  assert.ok(stateOutputInfo.isFile());
  assert.ok(!stateOutputInfo.isSymbolicLink());
  const state=await import(`${pathToFileURL(stateOutput).href}?v=${Date.now()}`);
  const controller=new AbortController();
  const identity={productId:1,videoProjectId:2,selectionDigest:"1:10|2:11|3:12",jobId:4,resultArtifactId:null,operationId:5,controller};
  assert.equal(state.isCurrentCompositionOperation(identity,identity),true);
  assert.equal(state.selectionIdentity({3:12,1:10,2:11}),"1:10|2:11|3:12");
  assert.equal(state.exactCompositionResult({status:"SUCCEEDED",result_entity_type:"video_composition_artifact",result_entity_id:9}),9);
  assert.equal(state.exactCompositionResult({status:"SUCCEEDED",result_entity_type:"video_render_artifact",result_entity_id:9}),null);
  assert.equal(state.shouldPollComposition({status:"QUEUED"}),true);
  assert.equal(state.shouldPollComposition({status:"RUNNING"}),true);
  assert.equal(state.shouldPollComposition({status:"FAILED"}),false);
  controller.abort();
  assert.equal(state.isCurrentCompositionOperation(identity,identity),false);
  const panel=await fs.readFile(path.join(root,"src/components/video/VideoCompositionPanel.tsx"),"utf8");
  assert.ok(panel.includes("明确选择来源视频"));
  assert.ok(panel.includes("确定性静音 AAC 占位音轨"));
  assert.ok(!panel.includes("latest"));
  assert.ok(panel.includes("isPresentation"));
  console.log("Video Composition Queue: 11 checks passed");
} finally {
  if (path.dirname(out) !== root) {
    throw new Error("Unsafe test output directory");
  }
  await fs.rm(out, { recursive: true, force: true });
}
