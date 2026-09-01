import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const panel = readFileSync(new URL("../src/components/growth/GrowthOptimizationPanel.tsx", import.meta.url), "utf8");
assert.match(css, /\.growth-panel__controls input\[type="file"\]/);
assert.doesNotMatch(css, /\.growth-panel__controls input\s*\{/);
assert.match(panel, /className="growth-optimization__controls"/);
assert.doesNotMatch(panel, /className="growth-panel__controls"/);
assert.match(panel, /className="growth-number-field"/);
assert.match(css, /\.growth-workspace-page \.growth-panel\s*\{[^}]*color: #24324b/);
assert.match(css, /\.growth-workspace-page \.growth-panel button:disabled\s*\{[^}]*opacity: 1/);

function luminance(hex) {
  const channels = hex.match(/[a-f\d]{2}/gi).map(value => parseInt(value, 16) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
for (const background of ["ffffff", "f8f8ff", "f4fffb", "f7f9fc", "f3f8ff", "e2e8f0"]) {
  for (const foreground of ["24324b", "526078"]) {
    const contrast = (luminance(background) + 0.05) / (luminance(foreground) + 0.05);
    assert.ok(contrast >= 4.5, `${foreground} on ${background}: ${contrast}`);
  }
}
console.log("Growth readability: scoped light-panel colors, visible number inputs and 12 contrast pairs passed.");
