import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => readFileSync(join(root, ...parts), "utf8");
const outputDir = mkdtempSync(join(tmpdir(), "socialpilot-delivery-evidence-"));

try {
  const compiler = join(root, "node_modules", "typescript", "bin", "tsc");
  const selectorSource = join(
    root,
    "src",
    "components",
    "video",
    "selectPresentationDeliveryEvidence.ts",
  );
  const compiled = spawnSync(
    process.execPath,
    [
      compiler,
      selectorSource,
      "--target",
      "ES2022",
      "--module",
      "ES2022",
      "--moduleResolution",
      "Bundler",
      "--outDir",
      outputDir,
      "--skipLibCheck",
    ],
    { cwd: root, encoding: "utf8" },
  );
  assert.equal(compiled.status, 0, compiled.stderr || compiled.stdout);
  writeFileSync(join(outputDir, "package.json"), '{"type":"module"}', "utf8");
  const { selectPresentationDeliveryEvidence } = await import(
    pathToFileURL(join(outputDir, "selectPresentationDeliveryEvidence.js")).href
  );

  const task = (overrides = {}) => ({
    id: 4,
    product_id: 1,
    artifact_id: 1,
    status: "SUCCEEDED",
    privacy_status: "private",
    ...overrides,
  });

  assert.deepEqual(selectPresentationDeliveryEvidence([task()], 1, 1), [task()]);
  assert.deepEqual(
    selectPresentationDeliveryEvidence([task({ artifact_id: 2 })], 1, 1),
    [],
  );
  const exact = task({ id: 8 });
  assert.deepEqual(
    selectPresentationDeliveryEvidence(
      [
        task({ id: 1, product_id: 2 }),
        task({ id: 2, artifact_id: 2 }),
        task({ id: 3, status: "FAILED" }),
        task({ id: 4, privacy_status: "public" }),
        exact,
      ],
      1,
      1,
    ),
    [exact],
  );

const videosApi = read("src", "api", "videos.ts");
assert.match(
  videosApi,
  /`\/video-projects\/\$\{videoProjectId\}\/render-artifacts`/,
);
assert.doesNotMatch(videosApi, /mode[^\n]*presentation[\s\S]*return \[\]/);

const socialApi = read("src", "api", "social.ts");
assert.match(
  socialApi,
  /function listPublishTasks[\s\S]*apiClient\.get<PublishTask\[]>/,
);

const page = read("src", "pages", "ContentStudioPage.tsx");
assert.match(page, /snapshot\?\.video_project\?\.id/);
assert.match(page, /getVideoRenderArtifacts\(videoProjectId\)/);
assert.match(page, /liveWanxEnabled && !isPresentation/);
assert.doesNotMatch(page, /VITE_ENABLE_YOUTUBE_PUBLISHING/);
assert.match(
  page,
  /isPresentation[\s\S]*listPublishTasks\(productId, controller\.signal\)/,
);
assert.match(
  page,
  /selectPresentationDeliveryEvidence\(tasks, productId, playableArtifactId\)/,
);
assert.doesNotMatch(
  page,
  /createLiveVideoRender|publishYouTube|preflightYouTubePublish|refreshPublishTask/,
);

const output = read("src", "components", "video", "VerifiedWanxOutput.tsx");
assert.match(output, /getVideoRenderArtifactContentUrl\(artifact\.id\)/);
assert.match(output, /label="Artifact" value=\{`#\$\{artifact\.id\}`\}/);
assert.match(output, /label="Status" value="SUCCEEDED"/);

const evidence = read(
  "src",
  "components",
  "video",
  "PresentationDeliveryEvidence.tsx",
);
assert.match(evidence, /YouTube Private/);
assert.match(evidence, /PublishTask #\{task\.id\}/);
assert.match(evidence, /value="SUCCEEDED"/);
assert.match(evidence, /task\.completed_at/);
assert.match(evidence, /value=\{`#\$\{task\.artifact_id\}`\}/);
assert.match(evidence, /task\.provider_video_id \? "已记录" : "未记录"/);
assert.match(evidence, /当前 Artifact 没有匹配的 YouTube Private 成功记录/);
assert.doesNotMatch(
  evidence,
  /<button|<a\s|href=|connectYouTube|preflightYouTubePublish|publishYouTube|refreshPublishTask|disconnectSocialAccount/,
);

const app = read("src", "App.tsx");
assert.match(
  app,
  /isPresentation[\s\S]*Navigate[\s\S]*mode=presentation/,
);

console.log(
  "Presentation artifact frontend checks passed: exact delivery evidence, empty state, gates and provider controls isolated",
);
} finally {
  rmSync(outputDir, { recursive: true, force: true });
}
