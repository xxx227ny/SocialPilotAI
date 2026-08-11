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
let scenarios = 0;
function check(actual, expected, label) {
  assert.deepEqual(actual, expected, label);
  scenarios += 1;
}
function matches(value, pattern, label) {
  assert.match(value, pattern, label);
  scenarios += 1;
}
function excludes(value, pattern, label) {
  assert.doesNotMatch(value, pattern, label);
  scenarios += 1;
}

try {
  const state = await server.ssrLoadModule(
    "/src/components/product/socialPublishingState.ts",
  );
  const digest = "a".repeat(64);
  const refreshDigest = "b".repeat(64);
  const job = (overrides = {}) => ({
    id: 9,
    job_type: state.YOUTUBE_PUBLISH_SUBMIT_V1,
    source_type: "product",
    source_id: 4,
    input_digest: digest,
    input_payload: {
      product_id: 4,
      social_account_id: 5,
      artifact_id: 6,
      publish_task_id: 12,
      frozen_input_digest: digest,
    },
    status: "QUEUED",
    result_entity_type: null,
    result_entity_id: null,
    ...overrides,
  });

  check(
    state.selectExactYouTubeSubmitJob([job()], 4, 5, 6, digest)?.id,
    9,
    "selects exact Submit Job",
  );
  for (const [label, overrides] of [
    ["wrong job type", { job_type: "other" }],
    ["wrong source type", { source_type: "publish_task" }],
    ["wrong source id", { source_id: 99 }],
    ["wrong digest", { input_digest: "c".repeat(64) }],
    ["missing payload", { input_payload: null }],
    ["wrong payload Product", { input_payload: { ...job().input_payload, product_id: 8 } }],
    ["wrong payload Account", { input_payload: { ...job().input_payload, social_account_id: 8 } }],
    ["wrong payload Artifact", { input_payload: { ...job().input_payload, artifact_id: 8 } }],
    ["wrong frozen digest", { input_payload: { ...job().input_payload, frozen_input_digest: "c".repeat(64) } }],
    ["missing PublishTask", { input_payload: { ...job().input_payload, publish_task_id: null } }],
    ["zero PublishTask", { input_payload: { ...job().input_payload, publish_task_id: 0 } }],
  ]) {
    check(
      state.selectExactYouTubeSubmitJob([job(overrides)], 4, 5, 6, digest),
      null,
      label,
    );
  }

  const refreshJob = (overrides = {}) => ({
    ...job(),
    job_type: state.YOUTUBE_PUBLISH_REFRESH_V1,
    source_type: "publish_task",
    source_id: 12,
    input_digest: refreshDigest,
    input_payload: {
      product_id: 4,
      social_account_id: 5,
      publish_task_id: 12,
      frozen_task_digest: refreshDigest,
    },
    ...overrides,
  });
  check(
    state.isExactYouTubeRefreshJob(refreshJob(), 4, 5, 12),
    true,
    "selects exact Refresh Job",
  );
  for (const [label, overrides] of [
    ["refresh wrong type", { job_type: "other" }],
    ["refresh wrong source", { source_type: "product" }],
    ["refresh wrong source id", { source_id: 13 }],
    ["refresh missing payload", { input_payload: null }],
    ["refresh wrong Product", { input_payload: { ...refreshJob().input_payload, product_id: 8 } }],
    ["refresh wrong Account", { input_payload: { ...refreshJob().input_payload, social_account_id: 8 } }],
    ["refresh wrong PublishTask", { input_payload: { ...refreshJob().input_payload, publish_task_id: 13 } }],
    ["refresh wrong digest", { input_digest: "c".repeat(64) }],
  ]) {
    check(
      state.isExactYouTubeRefreshJob(refreshJob(overrides), 4, 5, 12),
      false,
      label,
    );
  }

  const identity = (overrides = {}) => ({
    productId: 4,
    accountId: 5,
    artifactId: 6,
    inputDigest: digest,
    jobId: 9,
    publishTaskId: 12,
    operationId: 7,
    controller: new AbortController(),
    ...overrides,
  });
  const active = identity();
  for (const [status, expected] of [
    ["QUEUED", true],
    ["RUNNING", true],
    ["SUCCEEDED", false],
    ["FAILED", false],
    ["SUBMIT_UNKNOWN", false],
    ["CANCELED", false],
  ]) {
    check(
      state.youtubePublishJobNeedsPolling(job({ status })),
      expected,
      `${status} local polling`,
    );
  }
  check(
    state.shouldContinueYouTubePublishPolling(active, active, job()),
    true,
    "QUEUED reschedules",
  );
  check(
    state.shouldContinueYouTubePublishPolling(
      active,
      active,
      job({ status: "RUNNING" }),
    ),
    true,
    "RUNNING reschedules",
  );
  check(
    state.shouldContinueYouTubePublishPolling(active, active, "LOCAL_READ_ERROR"),
    true,
    "temporary local GET error reschedules same Job",
  );
  check(
    state.shouldContinueYouTubePublishPolling(active, active, job({ id: 10 })),
    false,
    "wrong response Job stops",
  );
  for (const [label, replacement] of [
    ["Product", identity({ productId: 8 })],
    ["Account", identity({ accountId: 8 })],
    ["Artifact", identity({ artifactId: 8 })],
    ["digest", identity({ inputDigest: "c".repeat(64) })],
    ["Job", identity({ jobId: 10 })],
    ["PublishTask", identity({ publishTaskId: 13 })],
    ["operation", identity({ operationId: 8 })],
    ["controller", identity({ controller: new AbortController() })],
  ]) {
    check(
      state.shouldContinueYouTubePublishPolling(
        active,
        replacement,
        "LOCAL_READ_ERROR",
      ),
      false,
      `${label} change invalidates old poll`,
    );
  }
  const aborted = identity();
  aborted.controller.abort();
  check(
    state.shouldContinueYouTubePublishPolling(
      aborted,
      aborted,
      "LOCAL_READ_ERROR",
    ),
    false,
    "aborted poll cannot reschedule",
  );

  check(
    state.exactPublishTaskResult(
      job({
        status: "SUCCEEDED",
        result_entity_type: "publish_task",
        result_entity_id: 12,
      }),
    ),
    12,
    "recovers exact PublishTask ID",
  );
  for (const [label, type, id] of [
    ["wrong result type", "video_render_task", 12],
    ["null result", "publish_task", null],
    ["zero result", "publish_task", 0],
    ["negative result", "publish_task", -1],
    ["fractional result", "publish_task", 1.5],
  ]) {
    check(
      state.exactPublishTaskResult(
        job({ status: "SUCCEEDED", result_entity_type: type, result_entity_id: id }),
      ),
      null,
      label,
    );
  }

  const succeededJob = job({
    status: "SUCCEEDED",
    result_entity_type: "publish_task",
    result_entity_id: 12,
  });
  check(
    state.canStartExactYouTubePublishResultRead(succeededJob, null),
    true,
    "exact result read can start",
  );
  check(
    state.canStartExactYouTubePublishResultRead(succeededJob, active),
    false,
    "duplicate exact result read is locked",
  );
  for (const [label, invalidJob] of [
    ["queued result", job({ status: "QUEUED", result_entity_type: "publish_task", result_entity_id: 12 })],
    ["running result", job({ status: "RUNNING", result_entity_type: "publish_task", result_entity_id: 12 })],
    ["failed result", job({ status: "FAILED", result_entity_type: "publish_task", result_entity_id: 12 })],
    ["unknown result", job({ status: "SUBMIT_UNKNOWN", result_entity_type: "publish_task", result_entity_id: 12 })],
    ["missing type", job({ status: "SUCCEEDED", result_entity_type: null, result_entity_id: 12 })],
    ["wrong type", job({ status: "SUCCEEDED", result_entity_type: "video_project", result_entity_id: 12 })],
    ["missing id", job({ status: "SUCCEEDED", result_entity_type: "publish_task", result_entity_id: null })],
    ["zero id", job({ status: "SUCCEEDED", result_entity_type: "publish_task", result_entity_id: 0 })],
    ["fractional id", job({ status: "SUCCEEDED", result_entity_type: "publish_task", result_entity_id: 1.5 })],
  ]) {
    check(
      state.canStartExactYouTubePublishResultRead(invalidJob, null),
      false,
      `${label} cannot reread`,
    );
  }

  let resultReadLock = null;
  let exactGetCalls = 0;
  let appliedTaskId = null;
  async function runExactRead(effect) {
    if (!state.canStartExactYouTubePublishResultRead(succeededJob, resultReadLock)) {
      return;
    }
    const requestIdentity = identity({
      operationId: 31,
      controller: new AbortController(),
    });
    resultReadLock = requestIdentity;
    exactGetCalls += 1;
    try {
      const taskResult = await effect();
      if (
        state.isCurrentExactYouTubePublishResultRead(
          requestIdentity,
          resultReadLock,
          succeededJob,
        )
      ) {
        appliedTaskId = taskResult.id;
      }
    } finally {
      if (state.canReleaseYouTubePublishLock(requestIdentity, resultReadLock)) {
        resultReadLock = null;
      }
    }
  }
  await assert.rejects(
    runExactRead(async () => { throw new Error("temporary local read failure"); }),
  );
  check(resultReadLock, null, "failed first read releases its own lock");
  check(
    state.canStartExactYouTubePublishResultRead(succeededJob, resultReadLock),
    true,
    "failed first read permits explicit reread",
  );
  await runExactRead(async () => ({ id: 12 }));
  check(exactGetCalls, 2, "explicit reread performs one additional exact GET");
  check(appliedTaskId, 12, "explicit reread applies original result entity ID");

  let releasePending;
  const pending = new Promise((resolve) => { releasePending = resolve; });
  const firstClick = runExactRead(async () => {
    await pending;
    return { id: 12 };
  });
  const callsWhileLocked = exactGetCalls;
  await runExactRead(async () => ({ id: 12 }));
  check(exactGetCalls, callsWhileLocked, "continuous click does not start a second GET");
  releasePending();
  await firstClick;

  const exactIdentity = identity({ operationId: 41 });
  check(
    state.isCurrentExactYouTubePublishResultRead(
      exactIdentity,
      exactIdentity,
      succeededJob,
    ),
    true,
    "exact result identity is current",
  );
  for (const [label, changedIdentity, changedJob] of [
    ["Product", { ...exactIdentity, productId: 8 }, succeededJob],
    ["Account", { ...exactIdentity, accountId: 8 }, succeededJob],
    ["Artifact", { ...exactIdentity, artifactId: 8 }, succeededJob],
    ["operation", { ...exactIdentity, operationId: 42 }, succeededJob],
    ["controller", { ...exactIdentity, controller: new AbortController() }, succeededJob],
    ["Job", exactIdentity, { ...succeededJob, id: 10 }],
    ["PublishTask", exactIdentity, { ...succeededJob, result_entity_id: 13 }],
  ]) {
    check(
      state.isCurrentExactYouTubePublishResultRead(
        exactIdentity,
        changedIdentity,
        changedJob,
      ),
      false,
      `${label} replacement invalidates old result success/error/finally`,
    );
  }
  const abortedResultRead = identity({ operationId: 41 });
  abortedResultRead.controller.abort();
  check(
    state.isCurrentExactYouTubePublishResultRead(
      abortedResultRead,
      abortedResultRead,
      succeededJob,
    ),
    false,
    "aborted result response is stale",
  );

  const replacement = identity({ operationId: 8, controller: new AbortController() });
  check(state.isCurrentYouTubePublishOperation(active, replacement), false, "old success ignored");
  check(state.isCurrentYouTubePublishOperation(active, replacement), false, "old error ignored");
  check(state.canReleaseYouTubePublishLock(active, replacement), false, "old finally keeps new lock");
  check(state.canReleaseYouTubePublishLock(replacement, replacement), true, "current finally releases lock");

  const load = new AbortController();
  const preflight = identity({ operationId: 11 });
  const submit = identity({ operationId: 12 });
  const refresh = identity({ operationId: 13 });
  const poll = identity({ operationId: 14 });
  const resultRead = identity({ operationId: 15 });
  state.cancelYouTubePublishControllers({
    load,
    preflight,
    submit,
    refresh,
    poll,
    resultRead,
  });
  for (const [label, controller] of [
    ["load", load],
    ["preflight", preflight.controller],
    ["submit", submit.controller],
    ["refresh", refresh.controller],
    ["poll", poll.controller],
    ["result read", resultRead.controller],
  ]) {
    check(controller.signal.aborted, true, `cleanup aborts ${label}`);
  }
  check(state.isCurrentYouTubePublishOperation(submit, submit), false, "aborted Submit is stale");
  check(state.isCurrentYouTubePublishOperation(refresh, refresh), false, "aborted Refresh is stale");
  check(state.canReleaseYouTubePublishLock(submit, replacement), false, "aborted old lock cannot release replacement");

  const panel = readFileSync(
    join(root, "src/components/product/SocialPublishingPanel.tsx"),
    "utf8",
  );
  const api = readFileSync(join(root, "src/api/social.ts"), "utf8");
  excludes(panel, /recoveredTasks\s*\[\s*0\s*\]/, "no recoveredTasks[0]");
  excludes(panel, /getLatest|latestPublish|latestTask/i, "no latest recovery");
  excludes(panel, /upload_video|initiate_upload_session|upload_media|get_video_status/, "no direct Provider call");
  matches(panel, /getYouTubePublishJob\(\s*active\.jobId![\s\S]*active\.controller\.signal/, "poll uses exact local Job GET");
  matches(panel, /shouldContinueYouTubePublishPolling[\s\S]*schedule\(\)/, "poll error can reschedule");
  const exactReadStart = panel.indexOf("async function readExactPublishTaskResult");
  const exactReadEnd = panel.indexOf("\n  async function enqueueRefresh", exactReadStart);
  assert.ok(exactReadStart >= 0 && exactReadEnd > exactReadStart, "exact result reader found");
  const exactReadSource = panel.slice(exactReadStart, exactReadEnd);
  matches(exactReadSource, /getPublishTask\(\s*active\.productId,\s*active\.publishTaskId!,\s*active\.controller\.signal/, "reread uses exact PublishTask ID");
  check((exactReadSource.match(/getPublishTask\(/g) ?? []).length, 1, "one local GET per result read");
  matches(exactReadSource, /isCurrentResultRead\(active\)/, "result read uses full identity guard");
  excludes(exactReadSource, /publishYouTube|refreshPublishTask|listPublishTasks|listYouTubePublishJobs|getYouTubePublishJob/, "reread performs no queue or list action");
  matches(panel, /onClick=\{\(\) => void readExactPublishTaskResult\(job\)\}/, "explicit exact reread button");
  matches(panel, /disabled=\{!canRereadExactResult \|\| resultReadState === "reading"\}/, "reread button lock");
  matches(panel, /正在读取精确 PublishTask 结果…/, "exact result reading copy is UTF-8");
  matches(panel, /重新读取精确 PublishTask 结果/, "exact result retry copy is UTF-8");
  const oldReadingCopy = new RegExp(Buffer.from("5aed772F5rmq55KH6K+y5b2H57uu5Ymn4oCYIFB1Ymxpc2hUYXNrIOe8geaStOeBiemIpVw/", "base64").toString("utf8"));
  const oldRetryCopy = new RegExp(Buffer.from("6Zay5baG5p+K55KH6K+y5b2H57uu5Ymn4oCYIFB1Ymxpc2hUYXNrIOe8geaStOeBiQ==", "base64").toString("utf8"));
  excludes(panel, oldReadingCopy, "old garbled reading copy removed");
  excludes(panel, oldRetryCopy, "old garbled retry copy removed");
  matches(panel, /submitRef\.current\s*!==\s*null/, "Submit double-click lock");
  matches(panel, /refreshRef\.current/, "Refresh double-click lock");
  matches(panel, /operationId\.current \+= 1;[\s\S]*cancelOperations\(\)/, "unmount invalidates and cancels operations");
  matches(panel, /useEffect\(\(\) => \{[\s\S]*\}, \[productId\]\);/, "Product change invalidates operations");
  matches(panel, /if \(isPresentation\) return null;/, "Presentation mode hides panel");
  matches(panel, /SUBMIT_UNKNOWN/, "SUBMIT_UNKNOWN is displayed as non-retryable");
  matches(api, /\/execution-jobs\/\$\{jobId\}/, "API polls local execution Job");
  excludes(api, /youtube\.com|googleapis\.com/, "API has no Provider endpoint");
  excludes(api, /timeout:\s*0/, "queue requests have bounded client behavior");

  console.log(`YouTube publish queue checks passed: ${scenarios} scenarios`);
} finally {
  await server.close();
}
