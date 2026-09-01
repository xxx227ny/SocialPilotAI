// Local-only UI fixture: all API responses are supplied by an in-memory adapter.
import { createServer } from "vite";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const server = await createServer({ cacheDir: mkdtempSync(join(tmpdir(), "socialpilot-read-resilience-")), server: { host: "127.0.0.1", port: 5189, strictPort: true }, plugins: [{
  name: "read-resilience-fixture",
  configureServer(vite) {
    vite.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/__read-resilience")) return next();
      const html = await vite.transformIndexHtml(req.url,
        '<!doctype html><html><head><meta charset="utf-8"><title>隔离读取容错验收</title></head><body><div id="root"></div><script type="module" src="/scripts/fixtures/read-resilience.tsx"></script></body></html>');
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(html);
    });
  },
}] });
await server.listen();
console.log("Read-only simulated UI: http://127.0.0.1:5189/__read-resilience");
