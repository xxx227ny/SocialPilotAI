import { createServer } from "vite";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const server = await createServer({
  cacheDir: mkdtempSync(join(tmpdir(), "socialpilot-growth-readability-")),
  server: { host: "127.0.0.1", port: 5191, strictPort: true },
  plugins: [{ name: "growth-readability-fixture", configureServer(vite) {
    vite.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/__growth-readability")) return next();
      const html = await vite.transformIndexHtml(req.url,
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>投流文字隔离验收</title></head><body><div id="root"></div><script type="module" src="/scripts/fixtures/growth-readability.tsx"></script></body></html>');
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(html);
    });
  } }],
});
await server.listen();
console.log("Read-only UI fixture: http://127.0.0.1:5191/__growth-readability");
