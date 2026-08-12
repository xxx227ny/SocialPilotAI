import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createServer } from "vite";
import ts from "typescript";

const root = process.cwd();
const server = await createServer({ appType: "custom", logLevel: "silent", root,
  server: { middlewareMode: true } });
let scenarios = 0;
const check = (actual, expected, label) => {
  assert.deepEqual(actual, expected, label); scenarios += 1;
};
const matches = (value, pattern, label) => {
  assert.match(value, pattern, label); scenarios += 1;
};
const excludes = (value, pattern, label) => {
  assert.doesNotMatch(value, pattern, label); scenarios += 1;
};

try {
  const state = await server.ssrLoadModule(
    "/src/components/product/tiktokAccountState.ts",
  );
  const panelSource = readFileSync(
    join(root, "src/components/product/SocialPublishingPanel.tsx"), "utf8",
  );
  const pureFunctions = panelSource.match(
    /export function shouldLoadSocialAccounts[\s\S]*?(?=export function SocialPublishingPanel)/,
  )?.[0];
  assert.ok(pureFunctions, "executable social account Gate helpers found");
  const transpiled = ts.transpileModule(pureFunctions, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const panelState = await import(
    `data:text/javascript;base64,${Buffer.from(transpiled).toString("base64")}`
  );
  for (const [label, gates, expected] of [
    ["YouTube only", [false, true, false, false, false, false], true],
    ["Instagram only", [false, false, true, false, false, false], true],
    ["TikTok only", [false, false, false, true, false, false], true],
    ["all account gates off", [false, false, false, false, false, false], false],
    ["Presentation YouTube", [true, true, false, false, false, false], false],
    ["Presentation Instagram", [true, false, true, false, false, false], false],
    ["Presentation TikTok", [true, false, false, true, false, false], false],
    ["YouTube publishing", [false, false, false, false, true, false], true],
    ["Instagram publishing", [false, false, false, false, false, true], true],
  ]) {
    check(
      panelState.shouldLoadSocialAccounts(...gates),
      expected,
      `${label} account-list decision`,
    );
  }
  const tiktokAccount = {
    id: 19,
    product_id: 7,
    platform: "tiktok",
    provider_account_id: "safe-test-id",
    display_name: "Competition TikTok",
    connection_status: "CONNECTED",
    scopes: ["user.info.basic", "video.publish"],
  };
  let accountRequests = 0;
  const loadTikTokOnlyAccounts = async () => {
    if (!panelState.shouldLoadSocialAccounts(false, false, false, true, false, false)) {
      return [];
    }
    accountRequests += 1;
    return [tiktokAccount];
  };
  const tiktokOnlyAccounts = await loadTikTokOnlyAccounts();
  check(accountRequests, 1, "TikTok-only mode calls local account GET once");
  check(
    panelState.findPlatformAccount(tiktokOnlyAccounts, "tiktok"),
    tiktokAccount,
    "TikTok-only response selects connected card account",
  );
  check(
    panelState.canLocallyDisconnectAccount(
      panelState.findPlatformAccount(tiktokOnlyAccounts, "tiktok"),
    ),
    true,
    "TikTok-only connected account enables local disconnect",
  );
  check(
    panelState.findPlatformAccount([tiktokAccount], "youtube"),
    undefined,
    "TikTok-only response does not impersonate YouTube",
  );
  const identity = (overrides = {}) => ({ productId: 7, accountId: 11,
    operationId: 3, controller: new AbortController(), ...overrides });
  const current = identity();
  check(state.isCurrentTikTokOperation(current, current), true, "exact identity");
  for (const [label, replacement] of [
    ["Product", identity({ productId: 8 })],
    ["Account", identity({ accountId: 12 })],
    ["operation", identity({ operationId: 4 })],
    ["controller", identity()],
  ]) {
    check(state.isCurrentTikTokOperation(current, replacement), false, label);
    check(state.canReleaseTikTokOperationLock(current, replacement), false,
      `${label} old finally cannot release replacement`);
  }
  current.controller.abort();
  check(state.isCurrentTikTokOperation(current, current), false, "abort invalidates");

  const connect = identity({ controller: new AbortController() });
  const disconnect = identity({ controller: new AbortController() });
  state.cancelTikTokOperations({ connect, disconnect });
  check(connect.controller.signal.aborted, true, "unmount abort connect");
  check(disconnect.controller.signal.aborted, true, "unmount abort disconnect");

  function navigationHarness() {
    let lock = null; let calls = 0; let assigns = 0; let operation = 0;
    return {
      async click(fetchUrl, assign) {
        if (!state.canStartTikTokOperation(lock, null)) return;
        const expected = identity({ operationId: ++operation,
          controller: new AbortController() });
        lock = expected; calls += 1; let navigated = false;
        try {
          const safe = state.safeTikTokAuthorizationUrl(await fetchUrl());
          if (!safe) throw new Error("unsafe");
          assigns += 1; assign(safe); navigated = true;
        } catch { /* local safe error */ }
        finally {
          if (state.shouldReleaseTikTokConnectLock(expected, lock, navigated)) {
            lock = null;
          }
        }
      },
      unmount() { const previous = lock; state.cancelTikTokOperations({ connect: lock,
        disconnect: null }); lock = null; return previous; },
      snapshot() { return { lock, calls, assigns }; },
    };
  }
  const official = "https://www.tiktok.com/v2/auth/authorize/?state=fake";
  const success = navigationHarness();
  await success.click(async () => official, () => {});
  await success.click(async () => official, () => {});
  check(success.snapshot().calls, 1, "navigation double click blocked");
  check(success.snapshot().assigns, 1, "assign once");
  check(success.snapshot().lock !== null, true, "lock held through navigation");
  const navigating = success.unmount();
  check(navigating.controller.signal.aborted, true, "navigation aborted on unmount");

  const assignError = navigationHarness();
  await assignError.click(async () => official, () => { throw new Error("blocked"); });
  check(assignError.snapshot().lock, null, "assign failure unlocks");
  await assignError.click(async () => official, () => {});
  check(assignError.snapshot().calls, 2, "assign failure allows retry");

  const unsafe = navigationHarness();
  await unsafe.click(async () => "https://evil.example/v2/auth/authorize/", () => {});
  check(unsafe.snapshot().assigns, 0, "unsafe URL no navigation");
  check(unsafe.snapshot().lock, null, "unsafe URL unlocks");

  check(state.safeTikTokAuthorizationUrl(official)?.startsWith(
    "https://www.tiktok.com/v2/auth/authorize/"), true, "official URL accepted");
  for (const [label, url] of [
    ["http", "http://www.tiktok.com/v2/auth/authorize/"],
    ["subdomain", "https://auth.www.tiktok.com/v2/auth/authorize/"],
    ["similar", "https://www.tiktok.com.evil.test/v2/auth/authorize/"],
    ["old path", "https://www.tiktok.com/auth/authorize/"],
    ["userinfo", "https://user@www.tiktok.com/v2/auth/authorize/"],
    ["fragment", "https://www.tiktok.com/v2/auth/authorize/#token"],
  ]) check(state.safeTikTokAuthorizationUrl(url), null, label);

  for (const status of ["connected", "denied", "failed"]) {
    check(state.readTikTokOAuthStatus(`?tiktok_oauth=${status}`), status, status);
  }
  for (const invalid of ["token", "provider_error", "", "CONNECTED"]) {
    check(state.readTikTokOAuthStatus(`?tiktok_oauth=${invalid}`), null, invalid);
  }
  check(state.readTikTokOAuthStatus("?instagram_oauth=connected"), null,
    "other platform callback isolated");
  check(state.tiktokScopeSummary(["user.info.basic", "video.publish"]),
    "基础身份 · 视频发布权限", "exact safe scopes");
  check(state.tiktokScopeSummary(["user.info.basic"]), "授权范围不完整",
    "missing scope");
  check(state.tiktokScopeSummary(["user.info.basic", "video.publish", "secret"]),
    "基础身份 · 视频发布权限", "unknown scope hidden");

  const panel = readFileSync(join(root, "src/components/product/SocialPublishingPanel.tsx"), "utf8");
  const api = readFileSync(join(root, "src/api/social.ts"), "utf8");
  const types = readFileSync(join(root, "src/types/social.ts"), "utf8");
  const features = readFileSync(join(root, "src/config/features.ts"), "utf8");
  matches(panel, /cancelTikTokOperations/, "unmount cleanup exists");
  matches(panel, /shouldReleaseTikTokConnectLock/, "navigation lock exists");
  matches(panel, /if \(isPresentation\) return null/, "Presentation hidden");
  matches(panel, /本地断开只清除本机 Token，不等于撤销 TikTok 侧授权/, "local only");
  matches(panel, /本地断开 TikTok/, "connected TikTok exposes local disconnect");
  matches(api, /\/social-accounts\/tiktok\/connect/, "connect endpoint");
  matches(api, /\/social-accounts\/tiktok\/\$\{accountId\}\/disconnect/, "disconnect endpoint");
  matches(features, /VITE_ENABLE_TIKTOK_ACCOUNT_BINDING/, "independent gate");
  matches(types, /"youtube" \| "instagram" \| "tiktok"/, "platform type");
  excludes(panel, /provider_account_id|access_token|refresh_token|open_id|client_secret|authorization_code/i,
    "sensitive identities not rendered");
  excludes(panel, /Direct Post|Creator Info|TikTok PublishTask/, "no publishing surface");
  console.log(`TikTok account binding frontend checks passed: ${scenarios} scenarios`);
} finally { await server.close(); }
