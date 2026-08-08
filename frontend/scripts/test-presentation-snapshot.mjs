import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createServer } from "vite";

const root = process.cwd();
const read = (...parts) => readFileSync(join(root, ...parts), "utf8");
const server = await createServer({
  appType: "custom",
  logLevel: "silent",
  root,
  server: { middlewareMode: true },
});

try {
  const state = await server.ssrLoadModule(
    "/src/components/product/presentationSnapshotState.ts",
  );
  const artifact = {
    artifact_id: 10,
    render_task_id: 9,
    video_project_id: 8,
    copy_matrix_id: 7,
    content_type: "video/mp4",
    size_bytes: 100,
    sha256: "a".repeat(64),
    created_at: "2026-08-08T00:00:00Z",
  };
  const project = {
    id: 8,
    product_id: 1,
    marketing_strategy_id: 6,
    copy_matrix_id: 7,
  };
  const exact = state.buildPresentationArtifactSources(1, [artifact], [project]);
  assert.equal(exact.length, 1);
  assert.equal(exact[0].marketing_strategy_id, 6);
  assert.equal(state.autoSelectedArtifactId(exact), 10);
  assert.equal(
    state.autoSelectedArtifactId([
      ...exact,
      { ...exact[0], artifact_id: 11 },
    ]),
    null,
  );
  assert.deepEqual(
    state.buildPresentationArtifactSources(
      1,
      [artifact],
      [{ ...project, copy_matrix_id: 99 }],
    ),
    [],
  );
  assert.deepEqual(
    state.buildPresentationArtifactSources(
      1,
      [artifact],
      [{ ...project, product_id: 2 }],
    ),
    [],
  );

  const task = {
    id: 12,
    product_id: 1,
    artifact_id: 10,
  };
  assert.deepEqual(
    state.matchingPublishTasks(
      [
        task,
        { ...task, id: 13, product_id: 2 },
        { ...task, id: 14, artifact_id: 11 },
      ],
      1,
      10,
    ).map((item) => item.id),
    [12],
  );

  const request = state.buildPresentationSnapshotRequest(exact[0], 12, [3, 1, 3]);
  assert.equal(request.marketing_brief_id, null);
  assert.equal(request.marketing_strategy_id, 6);
  assert.equal(request.copy_matrix_id, 7);
  assert.equal(request.video_project_id, 8);
  assert.equal(request.render_task_id, 9);
  assert.equal(request.artifact_id, 10);
  assert.equal(request.publish_task_id, 12);
  assert.deepEqual(request.campaign_ids, [1, 3]);

  const snapshot = {
    id: 20,
    ...request,
    campaign_ids: [1, 3],
  };
  assert.equal(
    state.findSameSourcePresentationSnapshot([snapshot], {
      ...request,
      campaign_ids: [3, 1],
    }).id,
    20,
  );
  assert.equal(
    state.findSameSourcePresentationSnapshot(
      [snapshot],
      { ...request, artifact_id: 99 },
    ),
    null,
  );

  const panel = read("src", "components", "product", "PresentationSnapshotPanel.tsx");
  assert.match(panel, /listPublishArtifacts\(productId/);
  assert.match(panel, /listPublishTasks\(productId/);
  assert.match(panel, /getFeedbackContext\(productId/);
  assert.match(panel, /getVideoProject\(videoProjectId/);
  assert.match(panel, /createInFlight\.current/);
  assert.match(panel, /sameSourceHistory/);
  assert.match(panel, /createPresentationSnapshot\(productId, request\)/);
  assert.doesNotMatch(
    panel,
    /if \(sameSourceHistory\)[\s\S]{0,240}return;/,
  );
  assert.match(panel, /result\.reused \? "reused" : "new"/);
  assert.match(panel, /同来源历史/);
  assert.match(panel, /MarketingBrief" missing/);
  assert.match(panel, /多个合法 Artifact/);
  assert.doesNotMatch(panel, /Qwen|Wanx|Google|YouTube/);

  const page = read("src", "pages", "ProductCenterPage.tsx");
  assert.match(
    page,
    /!isPresentation \? <PresentationSnapshotPanel productId=\{product\.id\} \/> : null/,
  );
  const api = read("src", "api", "presentationSnapshots.ts");
  assert.match(api, /apiClient\.post<PresentationSnapshotCreateResult>/);
  assert.match(api, /\/presentation-snapshots\/\$\{snapshotId\}/);
  assert.match(api, /apiClient\.get<PresentationSnapshot\[]>/);
  assert.doesNotMatch(api, /preflight|refresh|provider/i);

  console.log("Presentation Snapshot frontend checks passed: 35 checks");
} finally {
  await server.close();
}
