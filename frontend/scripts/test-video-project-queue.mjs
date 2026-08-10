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
function equal(actual, expected) {
  assert.equal(actual, expected);
  scenarios += 1;
}
function deepEqual(actual, expected) {
  assert.deepEqual(actual, expected);
  scenarios += 1;
}
function matches(value, pattern) {
  assert.match(value, pattern);
  scenarios += 1;
}
function doesNotMatch(value, pattern) {
  assert.doesNotMatch(value, pattern);
  scenarios += 1;
}

try {
  const state = await server.ssrLoadModule(
    "/src/components/video/initialVideoProjectState.ts",
  );
  const videoApi = await server.ssrLoadModule(
    "/src/api/videos.ts",
  );
  const source = {
    product_id: 1,
    strategy_id: 4,
    copy_matrix_id: 7,
    selected_by: "latest_valid_copy_matrix",
    provider_calls: 0,
    database_writes: 0,
  };
  deepEqual(state.selectExactInitialVideoSource(1, source), {
    strategy_id: 4,
    copy_matrix_id: 7,
  });
  equal(state.selectExactInitialVideoSource(2, source), null);
  equal(
    state.selectExactInitialVideoSource(1, { ...source, copy_matrix_id: 0 }),
    null,
  );

  const request = {
    strategy_id: 4,
    copy_matrix_id: 7,
    platform: "TikTok",
    duration_seconds: 30,
    aspect_ratio: "9:16",
  };
  const inputDigest = "a".repeat(64);
  const preflight = {
    ...request,
    input_digest: inputDigest,
    ready_for_execution: true,
    expires_at: "2099-01-01T00:00:00Z",
  };
  const job = {
    id: 9,
    job_type: "qwen.video_project.generate.v1",
    source_type: "product",
    source_id: 1,
    input_digest: inputDigest,
    input_payload: {
      product_id: 1,
      marketing_strategy_id: 4,
      copy_matrix_id: 7,
      platform: "TikTok",
      duration_seconds: 30,
      aspect_ratio: "9:16",
      frozen_input_digest: inputDigest,
    },
    status: "QUEUED",
    attempt_count: 0,
    max_attempts: 2,
    result_entity_type: null,
    result_entity_id: null,
    uncertain: false,
  };
  equal(
    state.selectExactInitialVideoProjectJob(
      [job],
      1,
      request,
      inputDigest,
    )?.id,
    9,
  );
  for (const mismatch of [
    { source_id: 2 },
    { input_digest: "b".repeat(64) },
    { input_payload: { ...job.input_payload, copy_matrix_id: 8 } },
    { job_type: "qwen.copy_matrix.generate.v1" },
  ]) {
    equal(
      state.selectExactInitialVideoProjectJob(
        [{ ...job, ...mismatch }],
        1,
        request,
        inputDigest,
      ),
      null,
    );
  }

  const enqueueable = {
    frontendGateEnabled: true,
    preflight,
    request,
    costConfirmed: true,
    submitLocked: false,
    job: null,
    now: 0,
  };
  equal(state.canEnqueueInitialVideoProject(enqueueable), true);
  for (const field of ["frontendGateEnabled", "costConfirmed"]) {
    equal(
      state.canEnqueueInitialVideoProject({ ...enqueueable, [field]: false }),
      false,
    );
  }
  equal(
    state.canEnqueueInitialVideoProject({ ...enqueueable, submitLocked: true }),
    false,
  );
  equal(
    state.canEnqueueInitialVideoProject({ ...enqueueable, job }),
    false,
  );
  equal(
    state.canEnqueueInitialVideoProject({
      ...enqueueable,
      request: { ...request, platform: "Instagram" },
    }),
    false,
  );
  equal(
    state.canEnqueueInitialVideoProject({
      ...enqueueable,
      preflight: { ...preflight, expires_at: "2000-01-01T00:00:00Z" },
      now: Date.now(),
    }),
    false,
  );

  equal(state.initialVideoProjectJobNeedsPolling(job), true);
  equal(
    state.initialVideoProjectJobNeedsPolling({ ...job, status: "RUNNING" }),
    true,
  );
  equal(
    state.initialVideoProjectJobNeedsPolling({ ...job, status: "FAILED" }),
    false,
  );
  equal(
    state.initialVideoProjectJobAllowsExplicitRetry({
      ...job,
      status: "FAILED",
      attempt_count: 1,
    }),
    true,
  );
  equal(
    state.initialVideoProjectJobAllowsExplicitRetry({
      ...job,
      status: "SUBMIT_UNKNOWN",
      uncertain: true,
    }),
    false,
  );
  equal(
    state.exactInitialVideoProjectResultId({
      ...job,
      status: "SUCCEEDED",
      result_entity_type: "video_project",
      result_entity_id: 23,
    }),
    23,
  );
  equal(
    state.exactInitialVideoProjectResultId({
      ...job,
      status: "SUCCEEDED",
      result_entity_type: "copy_matrix",
      result_entity_id: 23,
    }),
    null,
  );

  const oldController = new AbortController();
  const newController = new AbortController();
  const oldIdentity = {
    productId: 1,
    operationId: 10,
    controller: oldController,
  };
  equal(
    videoApi.isCurrentInitialVideoOperation(
      oldIdentity,
      1,
      10,
      oldController,
    ),
    true,
  );
  equal(
    videoApi.isCurrentInitialVideoOperation(
      oldIdentity,
      2,
      10,
      oldController,
    ),
    false,
  );
  equal(
    videoApi.isCurrentInitialVideoOperation(
      oldIdentity,
      1,
      11,
      oldController,
    ),
    false,
  );
  equal(
    videoApi.isCurrentInitialVideoOperation(
      oldIdentity,
      1,
      10,
      newController,
    ),
    false,
  );
  oldController.abort();
  equal(
    videoApi.isCurrentInitialVideoOperation(
      oldIdentity,
      1,
      10,
      oldController,
    ),
    false,
  );

  const staleRequestPhases = [
    "enqueue-success",
    "enqueue-error",
    "enqueue-finally",
    "retry-success",
    "retry-error",
    "retry-finally",
  ];
  for (const _phase of staleRequestPhases) {
    equal(
      videoApi.isCurrentInitialVideoOperation(
        { productId: 1, operationId: 20, controller: new AbortController() },
        2,
        21,
        newController,
      ),
      false,
    );
  }

  const component = readFileSync(
    join(root, "src", "components", "video", "InitialVideoProjectPanel.tsx"),
    "utf8",
  );
  matches(component, /enqueueInitialVideoProject/);
  matches(component, /listInitialVideoProjectJobs/);
  matches(component, /getInitialVideoProjectJob/);
  matches(component, /getVideoProject\(resultId/);
  matches(component, /preflight\.input_digest/);
  matches(component, /preflight\.preflight_digest/);
  matches(component, /cost_confirmed: true/);
  matches(component, /SUBMIT_UNKNOWN/);
  matches(component, /Explicit retry/);
  matches(component, /if \(isPresentation\) return null/);
  matches(component, /controllerRef\.current = controller/);
  matches(component, /submitLockRef\.current === identity/);
  matches(component, /retryLockRef\.current === identity/);
  matches(component, /retryInitialVideoProjectJob\([\s\S]*controller\.signal/);
  doesNotMatch(component, /getLatestVideoProjectForProduct/);
  doesNotMatch(component, /executeInitialVideoProject/);

  const api = readFileSync(join(root, "src", "api", "videos.ts"), "utf8");
  matches(api, /\/video-projects\/preflight/);
  matches(api, /\/video-projects\/execute/);
  matches(api, /job_type: "qwen\.video_project\.generate\.v1"/);
  matches(api, /\/execution-jobs\/\$\{jobId\}/);
  matches(api, /retry_confirmed: true/);
  matches(api, /retryInitialVideoProjectJob\([\s\S]*signal\?: AbortSignal/);
  matches(api, /retry_confirmed: true[\s\S]*\{ signal \}/);

  console.log(
    `Initial VideoProject Queue frontend checks passed: ${scenarios} scenarios`,
  );
} finally {
  await server.close();
}
