import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8");
const context = readFileSync(new URL("../src/context/AuthContext.tsx", import.meta.url), "utf8");
const layout = readFileSync(new URL("../src/layouts/AppLayout.tsx", import.meta.url), "utf8");
const login = readFileSync(new URL("../src/pages/LoginPage.tsx", import.meta.url), "utf8");

assert.match(app, /if \(!authenticated\)/);
assert.match(app, /<LoginPage/);
assert.match(client, /withCredentials:\s*true/);
assert.match(client, /socialpilot:unauthorized/);
assert.match(context, /getAuthSession\(\)/);
assert.match(context, /logoutRequest\(\)/);
assert.match(layout, /退出登录/);
assert.match(login, /autoComplete="username"/);
assert.match(login, /autoComplete="current-password"/);
assert.doesNotMatch(login, /localStorage|sessionStorage/);

console.log("Demo auth frontend checks passed: 10 assertions.");
