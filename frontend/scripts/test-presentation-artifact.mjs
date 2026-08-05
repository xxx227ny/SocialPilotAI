import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => readFileSync(join(root, ...parts), "utf8");

const videosApi = read("src", "api", "videos.ts");
assert.match(
  videosApi,
  /`\/video-projects\/\$\{videoProjectId\}\/render-artifacts`/,
);
assert.doesNotMatch(videosApi, /mode[^\n]*presentation[\s\S]*return \[\]/);

const page = read("src", "pages", "ContentStudioPage.tsx");
assert.match(page, /snapshot\?\.video_project\?\.id/);
assert.match(page, /getVideoRenderArtifacts\(videoProjectId\)/);
assert.match(page, /liveWanxEnabled && !isPresentation/);
assert.doesNotMatch(page, /createLiveVideoRender|publishYouTube/);

const output = read("src", "components", "video", "VerifiedWanxOutput.tsx");
assert.match(output, /getVideoRenderArtifactContentUrl\(artifact\.id\)/);
assert.match(output, /label="Artifact" value=\{`#\$\{artifact\.id\}`\}/);
assert.match(output, /label="Status" value="SUCCEEDED"/);

const app = read("src", "App.tsx");
assert.match(
  app,
  /isPresentation[\s\S]*Navigate[\s\S]*mode=presentation/,
);

console.log(
  "Presentation artifact frontend checks passed: exact read-only artifact, controls hidden, social route isolated",
);
