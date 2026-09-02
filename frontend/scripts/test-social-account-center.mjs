import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("../src/api/social.ts", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const layout = readFileSync(new URL("../src/layouts/AppLayout.tsx", import.meta.url), "utf8");
const page = readFileSync(new URL("../src/pages/SocialAccountsPage.tsx", import.meta.url), "utf8");

assert.match(api, /\/social-accounts\/overview/);
assert.match(api, /\/local-disconnect/);
assert.match(api, /confirm_disconnect: true/);
assert.match(app, /settings\/social-accounts/);
assert.match(layout, /社媒账号/);
assert.match(page, /社媒账号中心/);
assert.match(page, /关联商品/);
assert.match(page, /解除本系统绑定/);
assert.match(page, /只会删除 SocialPilot 保存的授权信息/);
assert.match(page, /不会返回或展示平台访问令牌/);
assert.doesNotMatch(page, /access_token|refresh_token|ciphertext/);
assert.doesNotMatch(api, /localStorage|sessionStorage/);

console.log("Social account center frontend checks passed: 12 assertions.");
