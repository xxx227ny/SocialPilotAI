import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const assetsDirectory = fileURLToPath(new URL("../dist/assets/", import.meta.url));
const javascriptFiles = readdirSync(assetsDirectory, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
  .map((entry) => join(assetsDirectory, entry.name));

if (javascriptFiles.length === 0) {
  throw new Error("Production build contains no JavaScript asset");
}

const bundle = javascriptFiles.map((path) => readFileSync(path, "utf8")).join("\n");
const forbiddenLocalApi = "http://127.0.0.1:8000/api/v1";

if (bundle.includes(forbiddenLocalApi)) {
  throw new Error("Production bundle points visitors to a localhost API");
}
if (!bundle.includes("/api/v1")) {
  throw new Error("Production bundle does not contain the same-origin API path");
}

console.log("Production API base is same-origin and contains no localhost fallback.");
