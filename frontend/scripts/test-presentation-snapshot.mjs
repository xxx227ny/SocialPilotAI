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
  const presentationState = await server.ssrLoadModule(
    "/src/components/presentation/snapshotPresentationState.ts",
  );
  const payloadState = await server.ssrLoadModule(
    "/src/components/presentation/snapshotPresentationPayload.ts",
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
    state.buildPresentationArtifactSources(1, [
      { ...artifact, copy_matrix_id: null },
    ], [project]),
    [],
  );

  const brief = {
    id: 5,
    product_id: 1,
    audience: "Commuters",
    language: "English",
    platforms: ["TikTok"],
    tone: "Energetic",
    objective: "Awareness",
    target_markets: ["US"],
    created_at: "2026-08-08T00:00:00Z",
  };
  assert.equal(state.autoSelectedMarketingBriefId([]), null);
  assert.equal(state.autoSelectedMarketingBriefId([brief]), 5);
  assert.equal(
    state.autoSelectedMarketingBriefId([brief, { ...brief, id: 6 }]),
    null,
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
  const requestWithBrief = state.buildPresentationSnapshotRequest(
    exact[0],
    12,
    [3, 1, 3],
    5,
  );
  assert.equal(requestWithBrief.marketing_brief_id, 5);

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
  assert.match(panel, /listMarketingTasks\(productId/);
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
  assert.match(panel, /autoSelectedMarketingBriefId\(briefCandidates\)/);
  assert.match(panel, /briefs\.length > 1 && selectedBriefId === null/);
  assert.match(panel, /selectedBrief\.audience/);
  assert.match(panel, /selectedBrief\.language/);
  assert.match(panel, /selectedBrief\.platforms/);
  assert.match(panel, /selectedBrief\.created_at/);
  assert.match(panel, /selectedBriefId,/);
  assert.match(panel, /多个合法 Artifact/);
  assert.doesNotMatch(panel, /Qwen|Wanx|Google|YouTube/);

  const page = read("src", "pages", "ContentStudioPage.tsx");
  assert.match(page, /<PresentationSnapshotPanel productId=\{product\.id\} \/>/);
  assert.match(page, /高级制作与交付/);
  const api = read("src", "api", "presentationSnapshots.ts");
  assert.match(api, /apiClient\.post<PresentationSnapshotCreateResult>/);
  assert.match(api, /\/presentation-snapshots\/\$\{snapshotId\}/);
  assert.match(api, /apiClient\.get<PresentationSnapshot\[]>/);
  assert.doesNotMatch(api, /preflight|refresh|provider/i);

  assert.deepEqual(
    presentationState.parseSnapshotPresentationRoute("?mode=presentation"),
    { kind: "legacy" },
  );
  assert.deepEqual(
    presentationState.parseSnapshotPresentationRoute(
      "?mode=presentation&snapshot_id=12",
    ),
    { kind: "snapshot", snapshotId: 12 },
  );
  for (const invalid of ["", "0", "-1", "abc", "1.5", "999999999999999999999"]) {
    assert.equal(
      presentationState.parseSnapshotPresentationRoute(
        `?mode=presentation&snapshot_id=${invalid}`,
      ).kind,
      "invalid",
    );
  }
  assert.equal(
    presentationState.snapshotPresentationUrl(12),
    "/?mode=presentation&snapshot_id=12",
  );
  assert.match(panel, /href=\{snapshotPresentationUrl\(snapshot\.id\)\}/);
  assert.match(panel, /进入演示/);

  const frozenPayload = {
    product: { id: 1, name: "Portable Blender", category: "Kitchen", description: "Fresh anywhere", selling_points: ["Portable"], target_markets: ["US"] },
    marketing_brief: { id: 5, audience: "Commuters", language: "English", platforms: ["TikTok"], tone: "Energetic", objective: "Awareness" },
    marketing_strategy: { id: 6, positioning: "On-the-go wellness", audience_insights: ["Convenience"], angles: ["Portability"], risks: [], evidence: [] },
    copy_matrix: { id: 7, copies: [
      { platform: "TikTok", hook: "Blend anywhere", caption: "Fresh on the go", hashtags: ["PortableBlender"], cta: "Discover" },
      { platform: "Instagram", hook: "Daily blend", caption: "Charge and blend", hashtags: ["HealthyLifestyle"], cta: "See more" },
      { platform: "Facebook", hook: "Fresh made simple", caption: "Everyday blender", hashtags: ["EasyCleaning"], cta: "Learn more" },
    ] },
    video_project: { id: 8, platform: "TikTok", title: "Fresh Drinks", concept: "Portable routine", duration_seconds: 15, aspect_ratio: "9:16", status: "planned", cta: "Blend today", scenes: [
      { sequence: 1, duration_seconds: 5, shot_type: "Close-up", visual_description: "Blender", action: "Add fruit", narration: "Fresh follows you" },
    ] },
    render_task: { id: 9, status: "SUCCEEDED", provider_name: "wanx", duration_seconds: 15, aspect_ratio: "9:16", resolution: "720x1280" },
    artifact: { id: 10, video_render_task_id: 9, content_type: "video/mp4", size_bytes: 1048576, sha256: "a".repeat(64) },
    publish_task: { id: 12, artifact_id: 10, platform: "youtube", privacy_status: "private", status: "SUCCEEDED", completed_at: "2026-08-08T01:00:00Z" },
    campaigns: [
      { id: 1, platform: "TikTok", campaign_name: "Awareness", impressions: 1000, clicks: 100, conversions: 10, spend: 50, revenue: 200 },
      { id: 3, platform: "Instagram", campaign_name: "Retargeting", impressions: 500, clicks: 25, conversions: 5, spend: 25, revenue: 100 },
    ],
    campaign_metrics: { impressions: 1500, clicks: 125, conversions: 15, spend: 75, revenue: 300, ctr: 0.083333, conversion_rate: 0.12, cpa: 5, roas: 4 },
    growth_recommendation: { problems: ["CTR gap"], recommendations: ["Keep creative"], creative_suggestions: ["Lead with portability"], budget_suggestion: "Decision support only", summary: "Frozen recommendation" },
  };
  const presentationSnapshot = {
    id: 20,
    schema_version: 1,
    digest: "d".repeat(64),
    product_id: 1,
    marketing_brief_id: 5,
    marketing_strategy_id: 6,
    copy_matrix_id: 7,
    video_project_id: 8,
    render_task_id: 9,
    artifact_id: 10,
    publish_task_id: 12,
    campaign_ids: [1, 3],
    missing_sections: [],
    snapshot_payload: frozenPayload,
    artifact_sha256: "a".repeat(64),
    artifact_snapshot_path: "presentation-snapshots/20/artifact.mp4",
    created_at: "2026-08-08T00:00:00Z",
  };
  const view = payloadState.readSnapshotPresentationView(presentationSnapshot);
  assert.equal(view.product.name, "Portable Blender");
  assert.equal(view.brief.id, 5);
  assert.equal(view.strategy.id, 6);
  assert.equal(view.copyMatrixId, 7);
  assert.equal(payloadState.formatSnapshotCopyIdentity(1, 2), "Strategy #1 \u2192 CopyMatrix #2");
  assert.equal(payloadState.formatSnapshotCopyIdentity(null, 2), "\u6765\u6e90\u8eab\u4efd\u7f3a\u5931");
  assert.deepEqual(view.copies.map((copy) => copy.platform), ["TikTok", "Instagram", "Facebook"]);
  assert.equal(view.video.scenes[0].durationSeconds, 5);
  assert.equal(view.render.status, "SUCCEEDED");
  assert.equal(view.artifact.sha256, "a".repeat(64));
  assert.equal(view.publish.privacyStatus, "private");
  assert.equal(view.campaigns.length, 2);
  assert.equal(view.metrics.roas, 4);
  assert.equal(view.recommendation.rawSummary, "Frozen recommendation");
  const grouped = payloadState.groupSnapshotCampaignMetrics(view.campaigns);
  assert.deepEqual(grouped.map((item) => item.platform), ["TikTok", "Instagram"]);
  assert.equal(grouped[0].ctr, 0.1);
  assert.equal(grouped[0].conversionRate, 0.1);
  assert.equal(grouped[0].cpa, 5);
  assert.equal(grouped[0].roas, 4);

  frozenPayload.product.name = "Changed source";
  frozenPayload.copy_matrix.copies[0].caption = "Changed copy";
  frozenPayload.campaigns[0].clicks = 999;
  assert.equal(view.product.name, "Portable Blender");
  assert.equal(view.copies[0].caption, "Fresh on the go");
  assert.equal(view.campaigns[0].clicks, 100);

  const missing = payloadState.readSnapshotPresentationView({ ...presentationSnapshot, snapshot_payload: { product: { id: 1, name: "Only Product" } } });
  assert.equal(missing.product.name, "Only Product");
  assert.equal(missing.copyMatrixId, null);

  const app = read("src", "App.tsx");
  const snapshotPage = read("src", "pages", "SnapshotPresentationPage.tsx");
  assert.match(app, /parseSnapshotPresentationRoute\(location\.search\)/);
  assert.match(app, /snapshotRoute\.kind !== "legacy"/);
  assert.match(app, /<SnapshotPresentationPage route=\{snapshotRoute\} \/>/);
  assert.match(snapshotPage, /loadPresentationSnapshotOnce\(snapshotId\)/);
  assert.match(snapshotPage, /result\.id !== snapshotId/);
  assert.match(snapshotPage, /0 AI Calls/);
  assert.match(snapshotPage, /不会回退到其他快照或最新数据/);
  assert.doesNotMatch(
    snapshotPage,
    /getDemoSnapshot|listProducts|listPublishTasks|getVideoProject|getFeedbackContext|createPresentationSnapshot|preflight|refresh|oauth|upload/i,
  );
  assert.doesNotMatch(snapshotPage, /<button/);
  const slides = [
    "SnapshotOverviewSlide.tsx",
    "SnapshotCopySlide.tsx",
    "SnapshotVideoSlide.tsx",
    "SnapshotGrowthSlide.tsx",
  ].map((name) => read("src", "components", "presentation", name));
  const presentationSource = [snapshotPage, ...slides].join("\n");
  assert.match(slides[2], /getPresentationSnapshotArtifactPreviewUrl\(snapshot\.id\)/);
  assert.match(slides[1], /MissingCopyCard/);
  assert.match(slides[1], /formatSnapshotCopyIdentity/);
  assert.doesNotMatch(slides[1], /api\//);
  assert.equal((snapshotPage.match(/loadPresentationSnapshotOnce\(/g) ?? []).length, 1);
  assert.match(slides[3], /RecommendationCard/);
  assert.match(slides[3], /view\.campaigns\.length/);
  assert.doesNotMatch(presentationSource, /<button|href=|provider_video_id/i);
  assert.doesNotMatch(
    presentationSource,
    /getDemoSnapshot|listProducts|listPublishTasks|getVideoProject|getFeedbackContext|createPresentationSnapshot|preflight|refresh|oauth|upload/i,
  );
  assert.match(api, /presentationSnapshotLoads/);
  assert.match(api, /loadPresentationSnapshotOnce/);
  assert.match(snapshotPage, /snapshot_id=\$\{snapshotId\}/);
  assert.match(snapshotPage, /\/growth-copilot/);

  console.log("Presentation Snapshot frontend checks passed: 100 checks");
} finally {
  await server.close();
}
