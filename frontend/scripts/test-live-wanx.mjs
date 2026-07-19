import assert from "node:assert/strict";

import { createServer } from "vite";

const server = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: process.cwd(),
  server: { middlewareMode: true },
});

try {
  const {
    executeLiveGeneration,
    isLiveWanxDemoEnabled,
    selectLatestPlayableArtifact,
  } = await server.ssrLoadModule(
    "/src/components/video/liveWanxGeneration.ts",
  );

  assert.equal(isLiveWanxDemoEnabled(undefined), false);
  assert.equal(isLiveWanxDemoEnabled("false"), false);
  assert.equal(isLiveWanxDemoEnabled("true"), true);

  const existingArtifact = artifact(1, "https://example.invalid/one.mp4");
  const latestArtifact = artifact(2, "https://example.invalid/two.mp4");
  assert.equal(
    selectLatestPlayableArtifact([existingArtifact, latestArtifact]).id,
    latestArtifact.id,
  );

  let createCalls = 0;
  let refreshCalls = 0;
  let artifactReloads = 0;
  const statuses = [];
  const success = await executeLiveGeneration({
    videoProjectId: 7,
    create: async () => {
      createCalls += 1;
      return execution("PENDING", null);
    },
    refresh: async () => {
      refreshCalls += 1;
      return refreshCalls === 1
        ? execution("RUNNING", null)
        : execution("SUCCEEDED", latestArtifact);
    },
    onStatus: (status) => statuses.push(status),
    onArtifactReady: async () => {
      artifactReloads += 1;
    },
    isActive: () => true,
    wait: async () => {},
  });
  assert.equal(success.task.status, "SUCCEEDED");
  assert.equal(createCalls, 1);
  assert.equal(refreshCalls, 2);
  assert.equal(artifactReloads, 1);
  assert.deepEqual(statuses, ["PENDING", "RUNNING", "SUCCEEDED"]);

  const artifactsBeforeFailure = [existingArtifact];
  await assert.rejects(
    executeLiveGeneration({
      videoProjectId: 7,
      create: async () => {
        throw new Error("safe simulated failure");
      },
      refresh: async () => execution("FAILED", null),
      onStatus: () => {},
      onArtifactReady: async () => {
        throw new Error("must not reload artifacts after failure");
      },
      isActive: () => true,
      wait: async () => {},
    }),
  );
  assert.equal(
    selectLatestPlayableArtifact(artifactsBeforeFailure).id,
    existingArtifact.id,
  );

  console.log("Live Wanx frontend checks passed: 4 scenarios");
} finally {
  await server.close();
}

function artifact(id, providerOutputUrl) {
  return {
    id,
    video_render_task_id: id,
    provider_output_url: providerOutputUrl,
    storage_path: null,
    metadata: {},
    expires_at: null,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
  };
}

function execution(status, renderArtifact) {
  return {
    task: { id: 10, status },
    artifact: renderArtifact,
    external_call: true,
  };
}
