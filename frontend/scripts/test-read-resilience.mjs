import assert from "node:assert/strict";
import axios from "axios";
import { createServer } from "vite";

const server = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
let checks = 0;
try {
  const { installReadResilience, READ_TIMEOUT_MS, waitForReadRetry } = await server.ssrLoadModule("/src/api/readResilience.ts");
  const { failedReadState, initialReadState } = await server.ssrLoadModule("/src/hooks/useReadResource.ts");
  const { getApiErrorMessage } = await server.ssrLoadModule("/src/api/client.ts");
  async function scenario({ method = "get", status, code = "ERR_NETWORK", recover = false, url = "/products", cancel = false }) {
    let calls = 0;
    let waits = 0;
    const controller = new AbortController();
    const client = axios.create({ timeout: 5000, adapter: async config => {
      calls++;
      assert.equal(config.timeout, method === "get" || method === "head" ? READ_TIMEOUT_MS : 5000);
      if (recover && calls === 2) return { status: 200, statusText: "OK", headers: {}, config, data: [{ id: 1 }] };
      throw new axios.AxiosError("fixture", code, config, {}, status ? { status, config, data: {}, headers: {}, statusText: "fixture" } : undefined);
    }});
    installReadResilience(client, async () => { waits++; if (cancel) controller.abort(); });
    try { await client.request({ method, url, signal: controller.signal }); } catch {}
    return { calls, waits };
  }
  assert.deepEqual(await scenario({ recover: true }), { calls: 2, waits: 1 }); checks++;
  assert.deepEqual(await scenario({}), { calls: 2, waits: 1 }); checks++;
  for (const status of [408, 502, 503, 504, 520, 521, 522, 523, 524]) {
    assert.deepEqual(await scenario({ status }), { calls: 2, waits: 1 }); checks++;
  }
  for (const method of ["post", "put", "patch", "delete"]) {
    assert.deepEqual(await scenario({ method, status: 502 }), { calls: 1, waits: 0 }); checks++;
  }
  for (const status of [400, 401, 403, 404, 409, 422, 429, 500]) {
    assert.deepEqual(await scenario({ status }), { calls: 1, waits: 0 }); checks++;
  }
  assert.deepEqual(await scenario({ url: "/auth/session" }), { calls: 1, waits: 0 }); checks++;
  assert.deepEqual(await scenario({ cancel: true }), { calls: 1, waits: 1 }); checks++;
  assert.deepEqual(await scenario({ code: "ERR_CANCELED" }), { calls: 1, waits: 0 }); checks++;
  const ac = new AbortController();
  const waiting = waitForReadRetry(10_000, ac.signal);
  ac.abort();
  await assert.rejects(waiting, error => axios.isCancel(error)); checks++;
  const snapshot = { key: "product:1", data: { id: 1 }, loadedAt: 123, error: null, loading: true };
  const retained = failedReadState(snapshot, new axios.AxiosError("timeout", "ECONNABORTED"));
  assert.deepEqual(retained.data, { id: 1 });
  assert.equal(retained.loadedAt, 123); checks++;
  assert.equal(initialReadState("product:2").data, null); checks++;
  for (const status of [401, 403, 404, 410]) {
    const missing = failedReadState(snapshot, new axios.AxiosError("missing", "ERR_BAD_REQUEST", {}, {}, { status }));
    assert.equal(missing.data, null);
    assert.equal(missing.loadedAt, null); checks++;
  }
  assert.match(getApiErrorMessage(new axios.AxiosError("timeout", "ECONNABORTED", { method: "get" }), "fallback"), /无需更换 API Key/); checks++;
  assert.match(getApiErrorMessage(new axios.AxiosError("timeout", "ECONNABORTED", { method: "post" }), "fallback"), /不要连续重复提交/); checks++;
  console.log(`Read resilience: ${checks} checks passed (bounded GET retries, no mutation replay, cancellation, stale data, authorization/missing records).`);
} finally { await server.close(); }
