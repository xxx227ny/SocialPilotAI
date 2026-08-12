import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createServer } from "vite";

const server = await createServer({ appType: "custom", logLevel: "silent", root: process.cwd(), server: { middlewareMode: true } });
let scenarios = 0;
const check = (actual, expected, label) => { assert.deepEqual(actual, expected, label); scenarios += 1; };
try {
  const state = await server.ssrLoadModule("/src/components/product/instagramPublishingState.ts");
  const controller = new AbortController();
  const identity = { productId: 1, accountId: 2, artifactId: 3, jobId: 4, taskId: 5, operationId: 6, controller };
  check(state.isCurrentInstagramPublishOperation(identity, identity), true, "current identity");
  check(state.canReleaseInstagramPublishLock(identity, { ...identity }), false, "old finally cannot release replacement");
  controller.abort();
  check(state.isCurrentInstagramPublishOperation(identity, identity), false, "aborted identity invalid");
  const controllers = [new AbortController(), new AbortController(), new AbortController(), new AbortController(), new AbortController()];
  state.cancelInstagramPublishingOperations(controllers.map((item, index) => ({ ...identity, operationId: index, controller: item })));
  controllers.forEach((item) => check(item.signal.aborted, true, "controller cancelled"));
  const job = (overrides = {}) => ({ id: 4, job_type: state.INSTAGRAM_PUBLISH_SUBMIT_V1, source_type: "product", source_id: 1, input_digest: "a".repeat(64), input_payload: {}, status: "QUEUED", result_entity_type: null, result_entity_id: null, ...overrides });
  check(state.instagramJobNeedsPolling(job()), true, "queued polls");
  check(state.instagramJobNeedsPolling(job({ status: "RUNNING" })), true, "running polls");
  for (const status of ["SUCCEEDED", "FAILED", "SUBMIT_UNKNOWN", "CANCELLED"]) check(state.instagramJobNeedsPolling(job({ status })), false, `${status} stops`);
  check(state.isExactInstagramJob(job(), state.INSTAGRAM_PUBLISH_SUBMIT_V1, "product", 1), true, "exact submit identity");
  check(state.isExactInstagramJob(job({ source_id: 2 }), state.INSTAGRAM_PUBLISH_SUBMIT_V1, "product", 1), false, "cross product rejected");
  check(state.exactInstagramPublishTaskId(job({ status: "SUCCEEDED", result_entity_type: "publish_task", result_entity_id: 9 })), 9, "exact task result");
  for (const id of [null, 0, -1, 1.5]) check(state.exactInstagramPublishTaskId(job({ status: "SUCCEEDED", result_entity_type: "publish_task", result_entity_id: id })), null, "invalid result id");
  check(state.exactInstagramPublishTaskId(job({ status: "SUCCEEDED", result_entity_type: "artifact", result_entity_id: 9 })), null, "wrong result type");
  const sequence = ["QUEUED", "QUEUED", "RUNNING", "RUNNING", "SUCCEEDED"];
  check(
    sequence.map((status) => state.shouldAdvanceInstagramPollCycle(job({ status }), true)),
    [true, true, true, true, false],
    "each non-terminal response schedules the same Job and success stops",
  );
  check(
    [0, 1].map(() => state.shouldAdvanceInstagramPollCycle(job(), true)),
    [true, true],
    "consecutive local errors can schedule the same Job",
  );
  check(state.shouldAdvanceInstagramPollCycle(job(), false), false, "replaced identity cannot advance polling");
  check(state.isSameExactInstagramPollJob(job(), job()), true, "same exact poll Job accepted");
  for (const overrides of [{ id: 8 }, { source_id: 8 }, { source_type: "publish_task" }, { job_type: "other" }]) {
    check(state.isSameExactInstagramPollJob(job(), job(overrides)), false, "changed poll identity rejected");
  }
  const refreshJob = (status) => job({ job_type: state.INSTAGRAM_PUBLISH_REFRESH_V1, source_type: "publish_task", status });
  const finalizeJob = (status) => job({ job_type: state.INSTAGRAM_PUBLISH_FINALIZE_V1, source_type: "publish_task", status });
  check(state.canEnqueueInstagramRefresh("PROCESSING", refreshJob("FAILED")), true, "Refresh FAILED retains retryable exact Task");
  check(state.canEnqueueInstagramFinalize("READY_TO_PUBLISH", finalizeJob("FAILED")), true, "Finalize FAILED retains exact Task for new Preflight");
  for (const status of ["QUEUED", "RUNNING", "SUBMIT_UNKNOWN"]) {
    check(state.canEnqueueInstagramRefresh("PROCESSING", refreshJob(status)), false, `Refresh ${status} blocks repeat`);
    check(state.canEnqueueInstagramFinalize("READY_TO_PUBLISH", finalizeJob(status)), false, `Finalize ${status} blocks repeat`);
  }
  check(state.canEnqueueInstagramRefresh("READY_TO_PUBLISH", refreshJob("FAILED")), false, "Refresh requires PROCESSING Task");
  check(state.canEnqueueInstagramFinalize("PROCESSING", finalizeJob("FAILED")), false, "Finalize requires READY_TO_PUBLISH Task");
  const panel = readFileSync(join(process.cwd(), "src/components/product/InstagramPublishingPanel.tsx"), "utf8");
  for (const phrase of ["准备并上传 Reel", "刷新处理状态", "确认公开发布", "重新读取精确 PublishTask 结果", "单场景渲染 Artifact", "SUBMIT_UNKNOWN"]) check(panel.includes(phrase), true, phrase);
  check(panel.includes("setPollCycle((value) => value + 1)"), true, "poll error schedules same exact Job again");
  for (const forbidden of ["latest", "listPublishTasks", "media_publish", "provider_video_id"]) check(panel.includes(forbidden), false, `forbidden ${forbidden}`);
  console.log(`Instagram publish queue scenarios: ${scenarios} passed`);
} finally { await server.close(); }
