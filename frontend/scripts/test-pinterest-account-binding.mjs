import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createServer } from "vite";
import ts from "typescript";

const root = process.cwd();
const server = await createServer({ appType: "custom", logLevel: "silent", root,
  server: { middlewareMode: true } });
let scenarios = 0;
const check = (actual, expected, label) => { assert.deepEqual(actual, expected, label); scenarios += 1; };
let behavior = 0;
let pure = 0;
let staticAssertions = 0;
const behaviorCheck = (actual, expected, label) => {
  check(actual, expected, label); behavior += 1;
};
const pureCheck = (actual, expected, label) => {
  check(actual, expected, label); pure += 1;
};
try {
  const state = await server.ssrLoadModule("/src/components/product/pinterestAccountState.ts");
  const panel = readFileSync(join(root, "src/components/product/SocialPublishingPanel.tsx"), "utf8");
  const pureSource = panel.match(/export function shouldLoadSocialAccounts[\s\S]*?(?=export function SocialPublishingPanel)/)?.[0];
  const js = ts.transpileModule(pureSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  const panelState = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
  pureCheck(panelState.shouldLoadSocialAccounts(false, false, false, false, false, false, false, true), true, "Pinterest-only loads local accounts");
  pureCheck(panelState.shouldLoadSocialAccounts(true, false, false, false, false, false, false, true), false, "Presentation blocks Pinterest GET");
  pureCheck(panelState.shouldLoadSocialAccounts(false, false, false, false, false, false, false, false), false, "all gates off");
  const identity = (overrides = {}) => ({ productId: 1, accountId: 2, operationId: 3, controller: new AbortController(), ...overrides });
  const current = identity();
  pureCheck(state.isCurrentPinterestOperation(current, current), true, "exact operation");
  for (const changed of [identity({productId: 2}), identity({accountId: 3}), identity({operationId: 4}), identity()]) {
    pureCheck(state.isCurrentPinterestOperation(current, changed), false, "stale operation rejected");
    pureCheck(state.canReleasePinterestOperationLock(current, changed), false, "stale finally cannot unlock");
  }
  const connect = identity(), disconnect = identity();
  state.cancelPinterestOperations({connect, disconnect});
  pureCheck(connect.controller.signal.aborted, true, "connect aborted"); pureCheck(disconnect.controller.signal.aborted, true, "disconnect aborted");
  const official = "https://www.pinterest.com/oauth/?state=fake";
  pureCheck(state.safePinterestAuthorizationUrl(official)?.startsWith("https://www.pinterest.com/oauth/"), true, "official URL");
  for (const unsafe of ["http://www.pinterest.com/oauth/", "https://pinterest.com/oauth/", "https://www.pinterest.com.evil.test/oauth/", "https://user@www.pinterest.com/oauth/", "https://www.pinterest.com/oauth/#token"]) pureCheck(state.safePinterestAuthorizationUrl(unsafe), null, "unsafe URL");
  for (const status of ["connected", "denied", "failed"]) pureCheck(state.readPinterestOAuthStatus(`?pinterest_oauth=${status}`), status, status);
  pureCheck(state.readPinterestOAuthStatus("?tiktok_oauth=connected"), null, "cross-platform callback isolated");
  pureCheck(state.pinterestScopeSummary(["boards:read", "pins:read", "pins:write", "user_accounts:read"]), "读取账号身份 · 读取 Boards · 读取和创建 Pins", "explicit write scope summary");
  pureCheck(state.pinterestScopeSummary(["pins:read"]), "授权范围不完整", "missing scopes");

  const makeIdentity = (overrides = {}) => ({ productId: 7, accountId: 9,
    operationId: 1, controller: new AbortController(), ...overrides });
  const connectStore = () => ({ connect: null, disconnect: null });
  async function runConnect({ response = official, navigate = () => {}, reject = null } = {}) {
    const store = connectStore(); let requests = 0; let errors = 0;
    const identity = makeIdentity();
    const promise = state.coordinatePinterestConnect({ store, identity,
      request: async () => { requests += 1; if (reject) throw reject; return { authorization_url: response }; },
      navigate, onError: () => { errors += 1; }, });
    return { store, identity, promise, stats: () => ({ requests, errors }) };
  }
  const double = await runConnect();
  const second = await state.coordinatePinterestConnect({ store: double.store,
    identity: makeIdentity({ operationId: 2 }), request: async () => { throw new Error("must not call"); },
    navigate: () => {}, onError: () => {} });
  await double.promise;
  behaviorCheck(double.stats().requests, 1, "connect double click HTTP once");
  behaviorCheck(second, false, "connect second click rejected");
  behaviorCheck(double.store.connect !== null, true, "navigation success holds lock");

  const failed = await runConnect({ reject: new Error("http") }); await failed.promise;
  behaviorCheck(failed.stats(), { requests: 1, errors: 1 }, "HTTP failure reported once");
  behaviorCheck(failed.store.connect, null, "HTTP failure releases lock");
  const unsafeRun = await runConnect({ response: "https://evil.example/oauth/" }); await unsafeRun.promise;
  behaviorCheck(unsafeRun.stats().errors, 1, "unsafe URL rejected");
  behaviorCheck(unsafeRun.store.connect, null, "unsafe URL releases lock");
  const assignRun = await runConnect({ navigate: () => { throw new Error("assign"); } }); await assignRun.promise;
  behaviorCheck(assignRun.stats().errors, 1, "assign exception reported");
  behaviorCheck(assignRun.store.connect, null, "assign exception releases lock");

  for (const replacement of [makeIdentity({ productId: 8 }), makeIdentity({ accountId: 10 }),
    makeIdentity({ operationId: 2 }), makeIdentity()]) {
    const store = connectStore(); let updates = 0; let resolveOld;
    const old = makeIdentity();
    const oldPromise = state.coordinatePinterestConnect({ store, identity: old,
      request: async () => new Promise((resolve) => { resolveOld = resolve; }), navigate: () => { updates += 1; },
      onError: () => { updates += 1; } });
    store.connect = replacement;
    resolveOld({ authorization_url: official });
    await oldPromise;
    behaviorCheck(updates, 0, "replacement suppresses old success/error");
    behaviorCheck(store.connect, replacement, "old finally preserves replacement lock");
  }
  const abortedStore = connectStore(); const aborted = makeIdentity(); let abortedUpdates = 0;
  const abortedPromise = state.coordinatePinterestConnect({ store: abortedStore, identity: aborted,
    request: async () => { aborted.controller.abort(); return { authorization_url: official }; },
    navigate: () => { abortedUpdates += 1; }, onError: () => { abortedUpdates += 1; } });
  await abortedPromise;
  behaviorCheck(abortedUpdates, 0, "Abort suppresses connect updates");

  const disconnectStore = connectStore(); let disconnectRequests = 0; let successes = 0; let failures = 0;
  const disconnectIdentity = makeIdentity();
  let resolveDisconnect; const pendingDisconnect = new Promise((resolve) => { resolveDisconnect = resolve; });
  const disconnectPromise = state.coordinatePinterestDisconnect({ store: disconnectStore,
    identity: disconnectIdentity, request: async (signal) => { disconnectRequests += 1;
      behaviorCheck(signal, disconnectIdentity.controller.signal, "disconnect signal bound"); return pendingDisconnect; },
    onSuccess: () => { successes += 1; }, onError: () => { failures += 1; } });
  const disconnectSecond = await state.coordinatePinterestDisconnect({ store: disconnectStore,
    identity: makeIdentity({operationId: 2}), request: async () => { disconnectRequests += 1; },
    onSuccess: () => {}, onError: () => {} });
  resolveDisconnect({ id: 9 }); await disconnectPromise;
  behaviorCheck(disconnectRequests, 1, "disconnect double click HTTP once");
  behaviorCheck(disconnectSecond, false, "disconnect second click rejected");
  behaviorCheck(successes, 1, "disconnect success once");
  behaviorCheck(failures, 0, "disconnect no error");
  behaviorCheck(disconnectStore.disconnect, null, "disconnect current finally releases");

  const errorStore = connectStore(); let errorUpdates = 0;
  await state.coordinatePinterestDisconnect({ store: errorStore, identity: makeIdentity(),
    request: async () => { throw new Error("disconnect failed"); },
    onSuccess: () => { errorUpdates += 10; }, onError: () => { errorUpdates += 1; } });
  behaviorCheck(errorUpdates, 1, "disconnect error updates current operation once");
  behaviorCheck(errorStore.disconnect, null, "disconnect error releases current lock");

  const replacedDisconnectStore = connectStore(); const oldDisconnect = makeIdentity();
  const newDisconnect = makeIdentity({ operationId: 2 }); let replacedUpdates = 0;
  let resolveOldDisconnect;
  const oldDisconnectPromise = state.coordinatePinterestDisconnect({
    store: replacedDisconnectStore, identity: oldDisconnect,
    request: async () => new Promise((resolve) => { resolveOldDisconnect = resolve; }),
    onSuccess: () => { replacedUpdates += 1; }, onError: () => { replacedUpdates += 1; },
  });
  replacedDisconnectStore.disconnect = newDisconnect;
  resolveOldDisconnect({}); await oldDisconnectPromise;
  behaviorCheck(replacedUpdates, 0, "replacement suppresses old disconnect update");
  behaviorCheck(replacedDisconnectStore.disconnect, newDisconnect,
    "old disconnect finally preserves replacement lock");

  const abortDisconnectStore = connectStore(); const abortDisconnect = makeIdentity(); let disconnectUpdates = 0;
  await state.coordinatePinterestDisconnect({ store: abortDisconnectStore,
    identity: abortDisconnect, request: async () => { abortDisconnect.controller.abort(); return {}; },
    onSuccess: () => { disconnectUpdates += 1; }, onError: () => { disconnectUpdates += 1; } });
  behaviorCheck(disconnectUpdates, 0, "Abort suppresses disconnect updates");
  const unmountConnect = makeIdentity(), unmountDisconnect = makeIdentity();
  state.cancelPinterestOperations({ connect: unmountConnect, disconnect: unmountDisconnect });
  behaviorCheck(unmountConnect.controller.signal.aborted && unmountDisconnect.controller.signal.aborted,
    true, "unmount aborts both operations");

  assert.match(panel, /PinterestAccountCard/); staticAssertions += 1;
  assert.match(panel, /if \(isPresentation\) return null/); staticAssertions += 1;
  assert.match(panel, /将读取账号身份和 Boards，并读取和创建 Pins/); staticAssertions += 1;
  assert.match(panel, /本阶段尚不创建 Pin/); staticAssertions += 1;
  assert.match(panel, /Stage 4A6 独立 Preflight 与显式确认/); staticAssertions += 1;
  assert.doesNotMatch(panel, /provider_account_id|access_token|refresh_token|client_secret|authorization_code/i); staticAssertions += 1;
  const api = readFileSync(join(root, "src/api/social.ts"), "utf8");
  assert.match(api, /\/social-accounts\/pinterest\/connect/); staticAssertions += 1;
  assert.match(api, /\/social-accounts\/pinterest\/\$\{accountId\}\/disconnect/); staticAssertions += 1;
  console.log(`Pinterest account binding: ${behavior} production behavior scenarios; ${pure} pure-function scenarios; ${staticAssertions} static/safety assertions passed`);
} finally { await server.close(); }
