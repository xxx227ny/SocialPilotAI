import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(
  new URL("../src/components/dashboard/BusinessValueCalculator.tsx", import.meta.url),
  "utf8",
);
const dashboard = readFileSync(new URL("../src/pages/DashboardPage.tsx", import.meta.url), "utf8");

assert.match(dashboard, /<BusinessValueCalculator \/>/);
assert.match(component, /目标用户/);
assert.match(component, /核心痛点/);
assert.match(component, /落地方式/);
assert.match(component, /可规模化/);
assert.match(component, /hoursSaved \* hourlyCost/);
assert.match(component, /结果仅为透明公式测算，不冒充真实客户成效/);
assert.match(component, /所有计算均在浏览器本地完成/);
assert.doesNotMatch(component, /fetch\(|axios|apiClient|localStorage|sessionStorage/);

console.log("Business value calculator checks passed: transparent formulas, four business dimensions, no network writes.");
