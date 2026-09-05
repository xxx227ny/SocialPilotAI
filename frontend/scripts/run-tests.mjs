import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const directory = new URL("./", import.meta.url);
const tests = readdirSync(directory).filter((name) => /^test-.*\.mjs$/.test(name)).sort();
const failures = [];
for (const name of tests) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(name, directory))], {
    cwd: fileURLToPath(new URL("../", directory)),
    stdio: "inherit",
  });
  if (result.error || result.status !== 0) failures.push(name);
}
console.log(`${tests.length - failures.length}/${tests.length} test scripts passed.`);
if (failures.length) {
  console.error(`Failed: ${failures.join(", ")}`);
  process.exitCode = 1;
}
