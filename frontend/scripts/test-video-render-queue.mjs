import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createServer } from "vite";

const root = process.cwd();
const server = await createServer({ appType: "custom", logLevel: "silent", root, server: { middlewareMode: true } });
let scenarios = 0;
function check(actual, expected, label) { assert.deepEqual(actual, expected, label); scenarios += 1; }
function matches(value, pattern, label) { assert.match(value, pattern, label); scenarios += 1; }
function excludes(value, pattern, label) { assert.doesNotMatch(value, pattern, label); scenarios += 1; }

try {
  const state = await server.ssrLoadModule("/src/components/video/videoRenderQueueState.ts");
  const digest = "a".repeat(64);
  const job = (overrides = {}) => ({
    id: 9, job_type: state.WANX_VIDEO_RENDER_SUBMIT_V1,
    source_type: "video_project", source_id: 4, input_digest: digest,
    input_payload: { video_project_id: 4 }, status: "QUEUED",
    result_entity_type: null, result_entity_id: null, ...overrides,
  });

  check(state.selectExactVideoRenderSubmitJob([job()], 4, digest)?.id, 9, "exact job");
  for (const [label, overrides] of [
    ["wrong job type", { job_type: "other" }],
    ["wrong source type", { source_type: "render_task" }],
    ["wrong source id", { source_id: 5 }],
    ["wrong digest", { input_digest: "b".repeat(64) }],
    ["missing payload", { input_payload: null }],
    ["missing video project id", { input_payload: {} }],
    ["wrong payload video project id", { input_payload: { video_project_id: 5 } }],
  ]) check(state.selectExactVideoRenderSubmitJob([job(overrides)], 4, digest), null, label);

  const makeIdentity = (overrides = {}) => ({
    productId: 1, videoProjectId: 4, jobId: 9, renderTaskId: null,
    operationId: 7, controller: new AbortController(), ...overrides,
  });
  const poll = makeIdentity();
  for (const [status, expected] of [
    ["QUEUED", true], ["RUNNING", true], ["SUCCEEDED", false],
    ["FAILED", false], ["SUBMIT_UNKNOWN", false],
  ]) check(state.videoRenderJobNeedsPolling(job({ status })), expected, `${status} polling`);
  check(state.shouldContinueVideoRenderPolling(poll, poll, job()), true, "queued reschedules");
  check(state.shouldContinueVideoRenderPolling(poll, poll, job({ status: "RUNNING" })), true, "running reschedules");
  check(state.shouldContinueVideoRenderPolling(poll, poll, "LOCAL_READ_ERROR"), true, "GET error reschedules");
  for (const [label, changed] of [
    ["product", { productId: 2 }], ["project", { videoProjectId: 5 }],
    ["job", { jobId: 10 }], ["operation", { operationId: 8 }],
    ["controller", { controller: new AbortController() }],
  ]) check(state.shouldContinueVideoRenderPolling(poll, { ...poll, ...changed }, "LOCAL_READ_ERROR"), false, `${label} invalidates poll`);
  const aborted = makeIdentity(); aborted.controller.abort();
  check(state.shouldContinueVideoRenderPolling(aborted, aborted, "LOCAL_READ_ERROR"), false, "abort invalidates poll");
  check(state.shouldContinueVideoRenderPolling(poll, poll, job({ id: 10 })), false, "wrong response job");
  check(state.shouldContinueVideoRenderPolling(poll, poll, job({ status: "FAILED" })), false, "terminal response");

  const replacement = makeIdentity({ operationId: 8, controller: new AbortController() });
  check(state.isCurrentVideoRenderOperation(poll, replacement), false, "old success ignored");
  check(state.isCurrentVideoRenderOperation(poll, replacement), false, "old error ignored");
  check(state.canReleaseVideoRenderOperationLock(poll, replacement), false, "old finally keeps new lock");
  check(state.canReleaseVideoRenderOperationLock(replacement, replacement), true, "current finally releases");

  const loadController = new AbortController();
  const submitIdentity = makeIdentity({ operationId: 20 });
  const refreshIdentity = makeIdentity({ operationId: 21 });
  const pollIdentity = makeIdentity({ operationId: 22 });
  const resultReadIdentity = makeIdentity({ operationId: 23 });
  state.cancelVideoRenderRequestControllers({
    load: loadController,
    submit: submitIdentity,
    refresh: refreshIdentity,
    poll: pollIdentity,
    resultRead: resultReadIdentity,
  });
  check(loadController.signal.aborted, true, "unmount aborts load");
  check(submitIdentity.controller.signal.aborted, true, "unmount aborts submit");
  check(refreshIdentity.controller.signal.aborted, true, "unmount aborts refresh");
  check(pollIdentity.controller.signal.aborted, true, "unmount aborts poll");
  check(resultReadIdentity.controller.signal.aborted, true, "unmount aborts result read");
  for (const [label, identity] of [
    ["submit", submitIdentity], ["refresh", refreshIdentity],
    ["poll", pollIdentity], ["result read", resultReadIdentity],
  ]) check(state.isCurrentVideoRenderOperation(identity, identity), false, `canceled ${label} is stale`);
  check(state.shouldContinueVideoRenderPolling(pollIdentity, pollIdentity, "LOCAL_READ_ERROR"), false, "canceled poll cannot reschedule");
  check(state.canReleaseVideoRenderOperationLock(submitIdentity, replacement), false, "canceled identity cannot release replacement");

  check(state.exactVideoRenderResult(job({ status: "SUCCEEDED", result_entity_type: "video_render_task", result_entity_id: 12 })), { type: "video_render_task", id: 12 }, "task result");
  check(state.exactVideoRenderResult(job({ status: "SUCCEEDED", result_entity_type: "video_render_artifact", result_entity_id: 13 })), { type: "video_render_artifact", id: 13 }, "artifact result");
  for (const [label, type, id] of [
    ["illegal type", "video_project", 12], ["null id", "video_render_task", null],
    ["zero id", "video_render_task", 0], ["negative id", "video_render_task", -1],
    ["fractional id", "video_render_task", 1.5],
  ]) check(state.exactVideoRenderResult(job({ status: "SUCCEEDED", result_entity_type: type, result_entity_id: id })), null, label);
  check(state.canStartVideoRenderResultRead(null), true, "read starts");
  check(state.canStartVideoRenderResultRead(poll), false, "duplicate read blocked");
  check(state.canReleaseVideoRenderOperationLock(poll, poll), true, "failed read unlocks for reread");
  check(state.isCurrentVideoRenderOperation(poll, replacement), false, "old read success ignored");
  check(state.isCurrentVideoRenderOperation(poll, replacement), false, "old read error ignored");
  check(state.canReleaseVideoRenderOperationLock(poll, replacement), false, "old read finally keeps new lock");

  const preflight = { product_id: 1, marketing_strategy_id: 2, copy_matrix_id: 3,
    input_digest: digest, preflight_digest: "b".repeat(64), expires_at: "2099-01-01T00:00:00Z" };
  check(state.buildVideoRenderSubmitRequest(preflight), { product_id: 1, marketing_strategy_id: 2,
    copy_matrix_id: 3, input_digest: digest, preflight_digest: "b".repeat(64),
    preflight_expires_at: "2099-01-01T00:00:00Z", cost_confirmed: true }, "frozen submit identity");

  const panelSource = readFileSync(join(root, "src/components/video/VideoRenderPreflightPanel.tsx"), "utf8");
  const unmountStart = panelSource.indexOf("useEffect(() => {\n    return () => {");
  const unmountEnd = panelSource.indexOf("\n  }, []);", unmountStart);
  assert.ok(unmountStart >= 0 && unmountEnd > unmountStart, "dependency-free unmount cleanup found");
  const unmountSource = panelSource.slice(unmountStart, unmountEnd);
  for (const refName of [
    "loadControllerRef", "submitLockRef", "refreshLockRef",
    "pollIdentityRef", "resultReadLockRef",
  ]) matches(unmountSource, new RegExp(`${refName}\\.current`), `cleanup covers ${refName}`);
  matches(unmountSource, /operationIdRef\.current \+= 1/, "cleanup invalidates operation id");
  matches(unmountSource, /productId: -1/, "cleanup invalidates active context");
  excludes(unmountSource, /set[A-Z][A-Za-z]*\(/, "cleanup has no React state update");
  excludes(unmountSource, /executeVideoProjectRender/, "cleanup never submits");
  excludes(unmountSource, /refreshWorkspaceVideoRenderTask/, "cleanup never refreshes");
  excludes(unmountSource, /readExactLocalResult/, "cleanup never rereads result");
  excludes(unmountSource, /provider\.(submit|fetch)|wanx.*client/i, "cleanup never calls provider");
  excludes(panelSource, /getLatestVideoRenderTask/, "latest task removed");
  excludes(panelSource, /isVideoRenderTaskNotFound/, "latest helper removed");
  matches(panelSource, /finally\s*\{[\s\S]*shouldContinueVideoRenderPolling[\s\S]*scheduleNextPoll\(\)/, "poll errors reschedule");
  matches(panelSource, /getVideoRenderJob\(\s*identity\.jobId!,[\s\S]*controller\.signal/, "exact local job GET");
  const readStart = panelSource.indexOf("async function readExactLocalResult");
  const readEnd = panelSource.indexOf("\n  useEffect(", readStart);
  assert.ok(readStart >= 0 && readEnd > readStart, "reader found");
  const readSource = panelSource.slice(readStart, readEnd);
  matches(readSource, /getVideoRenderArtifactMetadata/, "exact artifact metadata");
  matches(readSource, /recoverVideoRenderTask/, "exact task read");
  excludes(readSource, /executeVideoProjectRender/, "reread never submits");
  excludes(readSource, /refreshWorkspaceVideoRenderTask/, "reread never refreshes");
  matches(panelSource, /if \(isPresentation\) return null/, "presentation hidden");
  excludes(panelSource, /createLiveVideoRender|provider\.(submit|fetch)|wanx.*client/i, "no direct provider");
  excludes(panelSource, /provider_task_id|provider_output_url|absolute.*path/i, "browser-safe fields");

  console.log(`Video Render Queue frontend checks passed: ${scenarios}`);
} finally { await server.close(); }
