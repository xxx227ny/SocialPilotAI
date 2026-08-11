import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createServer } from "vite";

const root = process.cwd();
const server = await createServer({
  appType: "custom",
  logLevel: "silent",
  root,
  server: { middlewareMode: true },
});
let scenarios = 0;
function check(actual, expected, label) {
  assert.deepEqual(actual, expected, label);
  scenarios += 1;
}
function matches(value, pattern, label) {
  assert.match(value, pattern, label);
  scenarios += 1;
}
function excludes(value, pattern, label) {
  assert.doesNotMatch(value, pattern, label);
  scenarios += 1;
}

try {
  const state = await server.ssrLoadModule(
    "/src/components/product/instagramAccountState.ts",
  );
  const identity = (overrides = {}) => ({
    productId: 7,
    accountId: 11,
    operationId: 3,
    controller: new AbortController(),
    ...overrides,
  });
  const current = identity();
  check(state.isCurrentInstagramOperation(current, current), true, "exact identity current");
  for (const [label, replacement] of [
    ["Product replacement", identity({ productId: 8 })],
    ["Account replacement", identity({ accountId: 12 })],
    ["operation replacement", identity({ operationId: 4 })],
    ["controller replacement", identity()],
  ]) {
    check(state.isCurrentInstagramOperation(current, replacement), false, label);
    check(state.canReleaseInstagramOperationLock(current, replacement), false, `${label} cannot release lock`);
  }
  current.controller.abort();
  check(state.isCurrentInstagramOperation(current, current), false, "aborted response invalid");

  const connect = identity({ controller: new AbortController() });
  const disconnect = identity({ operationId: 4, controller: new AbortController() });
  state.cancelInstagramOperations({ connect, disconnect });
  check(connect.controller.signal.aborted, true, "unmount aborts connect");
  check(disconnect.controller.signal.aborted, true, "unmount aborts disconnect");
  check(state.canReleaseInstagramOperationLock(connect, disconnect), false, "old finally cannot release replacement");

  function navigationHarness() {
    let connectLock = null;
    let disconnectLock = null;
    let operationId = 0;
    let connectCalls = 0;
    let assignCalls = 0;
    return {
      async click(fetchAuthorizationUrl, assign) {
        if (!state.canStartInstagramOperation(connectLock, disconnectLock)) return;
        const expected = identity({
          operationId: ++operationId,
          controller: new AbortController(),
        });
        connectLock = expected;
        connectCalls += 1;
        let navigationStarted = false;
        try {
          const value = await fetchAuthorizationUrl();
          const safeUrl = state.safeInstagramAuthorizationUrl(value);
          if (!safeUrl) throw new Error("unsafe URL");
          assignCalls += 1;
          assign(safeUrl);
          navigationStarted = true;
        } catch {
          // The component renders a safe local error; the harness only tests locks.
        } finally {
          if (
            state.shouldReleaseInstagramConnectLock(
              expected,
              connectLock,
              navigationStarted,
            )
          ) {
            connectLock = null;
          }
        }
      },
      replace(next) {
        connectLock = next;
      },
      unmount() {
        const previous = connectLock;
        state.cancelInstagramOperations({
          connect: connectLock,
          disconnect: disconnectLock,
        });
        connectLock = null;
        disconnectLock = null;
        return previous;
      },
      snapshot() {
        return { connectLock, connectCalls, assignCalls };
      },
    };
  }

  const successfulNavigation = navigationHarness();
  const officialUrl = "https://www.instagram.com/oauth/authorize?state=fake";
  await successfulNavigation.click(async () => officialUrl, () => {});
  await successfulNavigation.click(async () => officialUrl, () => {});
  check(successfulNavigation.snapshot().connectCalls, 1, "successful navigation blocks second Connect");
  check(successfulNavigation.snapshot().assignCalls, 1, "successful navigation assigns once");
  check(successfulNavigation.snapshot().connectLock !== null, true, "navigation keeps lock until unmount");
  const navigatingIdentity = successfulNavigation.unmount();
  check(navigatingIdentity.controller.signal.aborted, true, "unmount aborts navigating operation");
  check(successfulNavigation.snapshot().connectLock, null, "unmount clears navigating lock");

  const thrownAssign = navigationHarness();
  await thrownAssign.click(async () => officialUrl, () => { throw new Error("blocked navigation"); });
  check(thrownAssign.snapshot().connectLock, null, "assign error releases lock");
  await thrownAssign.click(async () => officialUrl, () => {});
  check(thrownAssign.snapshot().connectCalls, 2, "assign error permits explicit retry");

  const unsafeNavigation = navigationHarness();
  await unsafeNavigation.click(async () => "https://evil.example/oauth", () => {});
  check(unsafeNavigation.snapshot().assignCalls, 0, "unsafe URL never navigates");
  check(unsafeNavigation.snapshot().connectLock, null, "unsafe URL releases lock");

  const failedConnect = navigationHarness();
  await failedConnect.click(async () => { throw new Error("local HTTP failure"); }, () => {});
  check(failedConnect.snapshot().connectLock, null, "Connect HTTP failure releases lock");

  const oldNavigation = identity({ controller: new AbortController() });
  const replacementNavigation = identity({ operationId: 9, controller: new AbortController() });
  check(
    state.shouldReleaseInstagramConnectLock(
      oldNavigation,
      replacementNavigation,
      false,
    ),
    false,
    "old finally cannot release replacement navigation lock",
  );

  check(
    state.safeInstagramAuthorizationUrl("https://www.instagram.com/oauth/authorize?state=fake")?.startsWith("https://www.instagram.com/"),
    true,
    "official HTTPS authorization URL accepted",
  );
  for (const [label, url] of [
    ["HTTP URL", "http://www.instagram.com/oauth/authorize"],
    ["wrong host", "https://evil.example/oauth/authorize"],
    ["credential host trick", "https://www.instagram.com@evil.example/oauth"],
    ["invalid URL", "not-a-url"],
  ]) {
    check(state.safeInstagramAuthorizationUrl(url), null, label);
  }

  for (const status of ["connected", "denied", "failed"]) {
    check(state.readInstagramOAuthStatus(`?instagram_oauth=${status}`), status, `safe ${status} callback`);
  }
  for (const unsafe of ["token", "provider_error", "", "CONNECTED"]) {
    check(state.readInstagramOAuthStatus(`?instagram_oauth=${unsafe}`), null, `reject callback ${unsafe}`);
  }
  check(
    state.readInstagramOAuthStatus("?youtube_oauth=connected"),
    null,
    "YouTube callback cannot become Instagram result",
  );

  const exactScopes = [
    "instagram_business_basic",
    "instagram_business_content_publish",
  ];
  check(state.instagramScopeSummary(exactScopes), "基础身份 · 内容发布权限", "exact scopes summarized");
  check(state.instagramScopeSummary([exactScopes[0]]), "授权范围不完整", "missing scope safe");
  check(state.instagramScopeSummary([...exactScopes, "secret_scope"]), "基础身份 · 内容发布权限", "unknown scope not displayed");

  const panel = readFileSync(
    join(root, "src", "components", "product", "SocialPublishingPanel.tsx"),
    "utf8",
  );
  const stateSource = readFileSync(
    join(root, "src", "components", "product", "instagramAccountState.ts"),
    "utf8",
  );
  const api = readFileSync(join(root, "src", "api", "social.ts"), "utf8");
  const features = readFileSync(join(root, "src", "config", "features.ts"), "utf8");
  const types = readFileSync(join(root, "src", "types", "social.ts"), "utf8");
  matches(panel, /connectRef\.current !== null[\s\S]*disconnectRef\.current !== null/, "double-click lock exists");
  matches(panel, /isCurrentInstagramOperation\(identity, connectRef\.current\)/, "connect success and error identity guarded");
  matches(panel, /shouldReleaseInstagramConnectLock\([\s\S]*navigationStarted/, "connect finally preserves navigation lock");
  matches(panel, /window\.location\.assign\(safeUrl\);[\s\S]*navigationStarted = true/, "lock retained only after assign succeeds");
  matches(panel, /isCurrentInstagramOperation\(identity, disconnectRef\.current\)/, "disconnect identity guarded");
  matches(panel, /cancelInstagramOperations/, "unmount cancellation exists");
  matches(panel, /if \(isPresentation\) return null/, "Presentation hidden");
  matches(panel, /不等于在 Meta 侧撤销授权/, "local disconnect semantics visible");
  matches(api, /\/social-accounts\/instagram\/connect/, "connect API exact");
  matches(api, /\/social-accounts\/instagram\/\$\{accountId\}\/disconnect/, "disconnect API exact");
  matches(features, /VITE_ENABLE_INSTAGRAM_ACCOUNT_BINDING/, "independent frontend gate");
  matches(types, /platform: "youtube" \| "instagram"/, "platform union");
  matches(stateSource, /"instagram_business_basic"/, "new basic scope exact");
  matches(
    stateSource,
    /"instagram_business_content_publish"/,
    "new content-publish scope exact",
  );
  excludes(
    stateSource,
    /["']business_(?:basic|content_publish)["']/,
    "legacy scopes absent",
  );
  excludes(panel, /publishInstagram|InstagramPublisher|Instagram PublishTask/, "no Instagram publishing entry");
  excludes(panel, /business_basic["']|business_content_publish["']/, "no legacy scopes in panel");
  excludes(panel, /姝|璇|彇|绮|缁|灉|鈥|閲|柊/, "no common UTF-8 mojibake");

  console.log(`Instagram account binding frontend checks passed: ${scenarios} scenarios`);
} finally {
  await server.close();
}
