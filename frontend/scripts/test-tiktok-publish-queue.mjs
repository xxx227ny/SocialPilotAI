import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createServer } from "vite";

const root = process.cwd();
const server = await createServer({ appType: "custom", logLevel: "silent", root,
  server: { middlewareMode: true } });
let scenarios = 0;
const check = (actual, expected, label) => { assert.deepEqual(actual, expected, label); scenarios += 1; };
const decodeUtf8 = (value) => Buffer.from(value, "base64").toString("utf8");

try {
  const state = await server.ssrLoadModule("/src/components/product/tiktokPublishingState.ts");
  check(state.isFreshTikTokSnapshot("2099-01-01T00:00:00Z", 0), true, "fresh snapshot");
  check(state.isFreshTikTokSnapshot("2000-01-01T00:00:00Z"), false, "expired snapshot");
  for (const status of ["QUEUED", "RUNNING", "TRANSIENT_ERROR"])
    check(state.nextTikTokPollAction(status), "continue", `${status} continues serial polling`);
  for (const status of ["SUCCEEDED", "FAILED", "SUBMIT_UNKNOWN", "CANCELLED"])
    check(state.nextTikTokPollAction(status), "stop", `${status} stops polling`);
  check(state.exactTikTokResultId({ status: "SUCCEEDED", result_entity_type: "publish_task", result_entity_id: 4 }, "publish_task"), 4, "exact result");
  check(state.exactTikTokResultId({ status: "SUCCEEDED", result_entity_type: "other", result_entity_id: 4 }, "publish_task"), null, "wrong result rejected");
  const exact = { id: 8, job_type: state.TIKTOK_PUBLISH_SUBMIT_V1,
    source_type: "product", source_id: 3 };
  const jobIdentity = { jobId: 8, jobType: state.TIKTOK_PUBLISH_SUBMIT_V1,
    sourceType: "product", sourceId: 3 };
  check(state.isExactTikTokJob(exact, jobIdentity), true, "exact Job accepted");
  for (const [field, value] of [["id", 9], ["job_type", "other"],
    ["source_type", "other"], ["source_id", 4]])
    check(state.isExactTikTokJob({ ...exact, [field]: value }, jobIdentity), false, `${field} replacement rejected`);
  const op = { productId: 1, accountId: 2, snapshotId: 3, artifactId: 4,
    jobId: 5, taskId: 6, operationId: 7 };
  check(state.isCurrentTikTokOperation(op, { ...op }), true, "complete operation identity accepted");
  for (const field of Object.keys(op))
    check(state.isCurrentTikTokOperation(op, { ...op, [field]: op[field] + 1 }), false, `${field} switch rejects stale completion`);
  check(state.canReleaseTikTokOperation(4, 4), true, "current finally releases lock");
  check(state.canReleaseTikTokOperation(4, 5), false, "old finally preserves new lock");
  check(state.interactionSettings(
    { comment_disabled: false, duet_disabled: true, stitch_disabled: false },
    { comments: true, duet: true, stitch: false }),
    { disable_comment: false, disable_duet: true, disable_stitch: true },
    "capability matrix forces Provider-disabled ability off");
  check(state.disclosureValid(false, false), false, "no disclosure blocked");
  check(state.disclosureValid(false, true), false, "branded without organic blocked");
  check(state.disclosureValid(true, false), true, "organic disclosure accepted");
  check(state.disclosureValid(true, true), true, "combined disclosure accepted");
  check(state.canRefreshTikTokTask("PROCESSING", "FAILED"), true, "failed refresh permits explicit retry");
  check(state.canRefreshTikTokTask("PROCESSING", "RUNNING"), false, "running refresh blocks overlap");

  let behaviorScenarios = scenarios;
  const runProductionPoll = async ({ abortDuringWait = false, abortDuringGet = false,
    transientFailures = 0, statuses = ["QUEUED", "QUEUED", "RUNNING", "RUNNING", "SUCCEEDED"],
    contextCurrent = () => true, replacement = null } = {}) => {
    const controller = new AbortController();
    let gets = 0; let index = 0; let accepted = 0; let resultReads = 0;
    const identity = { jobId: 8, jobType: state.TIKTOK_PUBLISH_SUBMIT_V1,
      sourceType: "product", sourceId: 3 };
    const initial = { id: 8, job_type: identity.jobType, source_type: "product",
      source_id: 3, status: statuses[0] };
    const result = await state.runTikTokSerialPoll(initial, {
      signal: controller.signal, identity,
      wait: async () => { if (abortDuringWait) controller.abort(); return !controller.signal.aborted; },
      read: async () => {
        gets += 1;
        if (abortDuringGet) controller.abort();
        if (transientFailures > 0) { transientFailures -= 1; throw new Error("temporary"); }
        index += 1;
        return { ...initial, status: statuses[Math.min(index, statuses.length - 1)], ...replacement };
      },
      contextCurrent,
      accept: () => { accepted += 1; },
      transientError: () => {},
    });
    if (result) resultReads += 1;
    return { gets, accepted, resultReads, status: result?.status ?? null };
  };
  check(await runProductionPoll({ abortDuringWait: true }), { gets: 0, accepted: 0, resultReads: 0, status: null }, "abort during timer issues no GET");
  check(await runProductionPoll({ abortDuringGet: true }), { gets: 1, accepted: 0, resultReads: 0, status: null }, "abort during GET blocks updates and result read");
  check(await runProductionPoll(), { gets: 4, accepted: 4, resultReads: 1, status: "SUCCEEDED" }, "production poll handles repeated queued/running states");
  check(await runProductionPoll({ transientFailures: 1 }), { gets: 5, accepted: 4, resultReads: 1, status: "SUCCEEDED" }, "transient error continues exact Job");
  for (const replacement of [{ id: 9 }, { job_type: "other" }, { source_type: "other" }, { source_id: 4 }])
    check((await runProductionPoll({ replacement })).resultReads, 0, "replacement identity stops production poll");
  for (const field of ["productId", "accountId", "snapshotId", "artifactId", "taskId", "operationId"])
    check((await runProductionPoll({ contextCurrent: () => field === "never" })).gets, 0, `${field} context change stops production poll`);
  behaviorScenarios = scenarios - behaviorScenarios;
  const panel = readFileSync(join(root, "src/components/product/TikTokPublishingPanel.tsx"), "utf8");
  for (const endpoint of ["queryTikTokCreatorInfo", "preflightTikTokPublish", "publishTikTok", "refreshTikTokPublish"]) {
    check(panel.includes(endpoint), true, `${endpoint} wired`);
  }
  check(panel.includes("No fresh Creator Info snapshot"), true, "expired snapshot disables form");
  check(panel.includes("setTimeout"), true, "single serial timeout polling");
  check(panel.includes("setInterval"), false, "no overlapping interval polling");
  check(panel.includes("useEffect([job]"), false, "polling is not job-object-effect driven");
  check(panel.includes("重新读取精确 Creator Info 结果"), true, "snapshot exact retry exposed");
  check(panel.includes("重新读取精确 PublishTask 结果"), true, "task exact retry exposed");
  check(panel.includes("provider_publish_id"), false, "provider publish identity hidden");
  check(panel.includes("upload_url"), false, "upload URL hidden");
  check(panel.includes("latest"), false, "latest fallback forbidden");
  const oldMojibakePatterns = ["w4M=", "w4I=", "6ZSf5pak5ou3", "77+9"].map(decodeUtf8);
  for (const candidate of [panel,
    readFileSync(join(root, "src/components/product/tiktokPublishingState.ts"), "utf8"),
    readFileSync(join(root, "scripts/test-tiktok-publish-queue.mjs"), "utf8")])
    for (const pattern of oldMojibakePatterns)
      check(candidate.includes(pattern), false, "legacy mojibake pattern absent");
  const social = readFileSync(join(root, "src/components/product/SocialPublishingPanel.tsx"), "utf8");
  check(social.includes("isPresentation) return null"), true, "Presentation hides publishing");
  const staticAssertions = scenarios - behaviorScenarios;
  console.log(`TikTok publish queue: ${behaviorScenarios} production behavior scenarios; ${staticAssertions} static/safety assertions passed`);
} finally {
  await server.close();
}
