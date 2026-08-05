import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = mkdtempSync(join(tmpdir(), "socialpilot-social-state-"));

try {
  const compiler = join(root, "node_modules", "typescript", "bin", "tsc");
  const source = join(
    root,
    "src",
    "components",
    "product",
    "socialPublishingState.ts",
  );
  const compiled = spawnSync(
    process.execPath,
    [
      compiler,
      source,
      "--target",
      "ES2022",
      "--module",
      "NodeNext",
      "--moduleResolution",
      "NodeNext",
      "--outDir",
      output,
      "--skipLibCheck",
    ],
    { cwd: root, encoding: "utf8" },
  );
  assert.equal(compiled.status, 0, compiled.stderr || compiled.stdout);
  writeFileSync(join(output, "package.json"), '{"type":"module"}', "utf8");
  const state = await import(
    pathToFileURL(join(output, "socialPublishingState.js")).href
  );

  assert.equal(state.shouldLoadSocialData(true, true, true), false);
  assert.equal(state.shouldLoadSocialData(false, false, false), false);
  assert.equal(state.shouldLoadSocialData(false, true, false), true);
  assert.equal(state.shouldLoadPublishTaskHistory(true), false);
  assert.equal(state.shouldLoadPublishTaskHistory(false), true);
  assert.equal(
    state.canSubmitPrivateUpload({
      preflightReady: true,
      confirmed: true,
      uploadLocked: false,
      madeForKidsSelected: true,
      identityComplete: true,
    }),
    true,
  );
  for (const field of [
    "preflightReady",
    "confirmed",
    "madeForKidsSelected",
    "identityComplete",
  ]) {
    const guard = {
      preflightReady: true,
      confirmed: true,
      uploadLocked: false,
      madeForKidsSelected: true,
      identityComplete: true,
    };
    guard[field] = false;
    assert.equal(state.canSubmitPrivateUpload(guard), false);
  }
  assert.deepEqual(state.invalidatedAuthorization(), {
    preflightDigest: null,
    confirmed: false,
    result: null,
  });

  const component = readFileSync(
    join(root, "src", "components", "product", "SocialPublishingPanel.tsx"),
    "utf8",
  );
  const placeholder = component.match(
    /function PlatformPlaceholder[\s\S]*?function connectionLabel/,
  )?.[0];
  assert.ok(placeholder);
  assert.match(placeholder, /<button type="button" disabled>/);
  assert.doesNotMatch(placeholder, /onClick=/);

  const readOnlyHistory = component.match(
    /function ReadOnlyPublishTaskHistory[\s\S]*?function YouTubePublisher/,
  )?.[0];
  assert.ok(readOnlyHistory);
  assert.match(readOnlyHistory, /PublishTask #\{task\.id\}/);
  assert.match(readOnlyHistory, /task\.provider_video_id/);
  assert.match(readOnlyHistory, /task\.privacy_status/);
  assert.match(readOnlyHistory, /task\.completed_at/);
  assert.doesNotMatch(
    readOnlyHistory,
    /preflightYouTubePublish|publishYouTube|refreshPublishTask|<button/,
  );
  assert.match(component, /loadTaskHistory\s*\? listPublishTasks/);
  assert.match(component, /<ReadOnlyPublishTaskHistory tasks=\{tasks\} \/>/);
  assert.match(component, /readOnly=\{!youtubePublishingEnabled\}/);
  assert.match(component, /if \(isPresentation\) return null/);
  console.log("social publishing frontend state: 20 checks passed");
} finally {
  rmSync(output, { recursive: true, force: true });
}
