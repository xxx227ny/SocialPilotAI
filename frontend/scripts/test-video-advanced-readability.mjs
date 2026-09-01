import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

for (const selector of [
  ".initial-video-project",
  ".video-render-preflight",
  ".video-render-task-result",
]) {
  const start = css.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `${selector} must exist`);
  const block = css.slice(start, css.indexOf("}", start) + 1);
  assert.match(block, /color:\s*#1f2937/, `${selector} needs an explicit dark foreground`);
}

for (const fragment of [
  ".initial-video-project > header > strong",
  ".initial-video-project__controls label",
  ".initial-video-project__confirmation",
  ".initial-video-project button:disabled",
  ".video-render-preflight__future-action button:disabled",
  ".video-render-preflight__execution button:disabled",
]) {
  assert.ok(css.includes(fragment), `${fragment} readability rule must exist`);
}

function luminance(hex) {
  const rgb = hex.match(/[0-9a-f]{2}/gi).map((value) => Number.parseInt(value, 16) / 255);
  const linear = rgb.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground, background) {
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}

for (const [foreground, background] of [
  ["1f2937", "f8fbff"],
  ["475569", "f8fbff"],
  ["334155", "ffffff"],
  ["475569", "e2e8f0"],
  ["1e3a5f", "eff6ff"],
  ["1d4ed8", "dbeafe"],
]) {
  assert.ok(
    contrast(foreground, background) >= 4.5,
    `#${foreground} on #${background} must meet WCAG AA`,
  );
}

console.log("Advanced video readability: explicit light-card colors and 6 contrast pairs passed.");
