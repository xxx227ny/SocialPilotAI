import assert from "node:assert/strict";
import axios from "axios";
import { createServer } from "vite";

const server = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
try {
  const { getReadResource, clearReadResources, invalidateReadResources } = await server.ssrLoadModule("/src/hooks/readResourceStore.ts");
  clearReadResources();
  const resource = getReadResource("products");
  let calls = 0, finish;
  const loader = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
  const unsubscribe = resource.subscribe(() => {});
  const pending = resource.load(loader);
  await Promise.resolve();
  unsubscribe(); // Simulated route leave.
  assert.equal(getReadResource("products"), resource);
  assert.equal(resource.load(loader), pending); // Remount and focus join it.
  assert.equal(resource.load(loader, true), pending);
  assert.equal(calls, 1);
  finish([{ id: 1 }]); await pending;
  for (let i = 0; i < 10; i++) await getReadResource("products").load(loader);
  assert.equal(calls, 1);
  assert.deepEqual(resource.state.data, [{ id: 1 }]);
  const offline = () => Promise.reject(new axios.AxiosError("timeout", "ECONNABORTED"));
  await resource.load(offline, true);
  assert.deepEqual(resource.state.data, [{ id: 1 }]);
  assert.equal(resource.state.loading, false);
  assert.ok(resource.state.error);
  assert.equal(getReadResource("product:2").state.data, null);
  for (const status of [401, 403, 404, 410]) {
    resource.update([{ id: 1 }]);
    await resource.load(() => Promise.reject(new axios.AxiosError("gone", "ERR_BAD_REQUEST", {}, {}, { status })), true);
    assert.equal(resource.state.data, null);
  }
  let late;
  const old = resource.load(() => new Promise(resolve => { late = resolve; }), true);
  await Promise.resolve();
  resource.update([{ id: 2 }]);
  late([{ id: 999 }]); await old;
  assert.deepEqual(resource.state.data, [{ id: 2 }]);
  const stale = resource.load(() => new Promise(resolve => { late = resolve; }), true);
  await Promise.resolve();
  clearReadResources();
  late([{ id: 999 }]); await stale;
  assert.equal(resource.state.data, null);
  assert.equal(getReadResource("products").state.data, null);
  getReadResource("product:1").update({ id: 1 });
  getReadResource("products").update([{ id: 1 }]);
  invalidateReadResources("1");
  assert.equal(getReadResource("product:1").state.data, null);
  assert.equal(getReadResource("products").state.data, null);
  const before = getReadResource("bounded-test");
  const observed = getReadResource("auth-clear-race");
  let authReads = 0;
  const unobserve = observed.subscribe(() => {});
  await observed.load(async () => { authReads++; return [1]; });
  invalidateReadResources();
  clearReadResources();
  await Promise.resolve();
  assert.equal(authReads, 1, "logout cancels queued mutation revalidation");
  assert.equal(observed.state.data, null);
  unobserve();
  const active = getReadResource("mutation-refresh");
  let version = 1;
  const release = active.subscribe(() => {});
  const read = () => Promise.resolve(version);
  await active.load(read);
  version = 2;
  invalidateReadResources();
  await Promise.resolve();
  await active.load(read);
  assert.equal(active.state.data, 2, "mutation refreshes active subscribers");
  release();
  for (let i = 0; i < 110; i++) getReadResource(`dormant:${i}`);
  assert.notEqual(getReadResource("bounded-test"), before);
  console.log("Read cache tests passed: remount, 10 return visits, in-flight deduplication, offline retention, identity isolation, 401/403/404/410 eviction, mutation race, logout race, deletion and bounded cache.");
} finally { await server.close(); }
