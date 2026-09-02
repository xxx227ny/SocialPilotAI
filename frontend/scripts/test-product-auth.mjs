import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const authApi = readFileSync(new URL("../src/api/auth.ts", import.meta.url), "utf8");
const credentialApi = readFileSync(new URL("../src/api/credentials.ts", import.meta.url), "utf8");
const context = readFileSync(new URL("../src/context/AuthContext.tsx", import.meta.url), "utf8");
const login = readFileSync(new URL("../src/pages/LoginPage.tsx", import.meta.url), "utf8");
const settings = readFileSync(new URL("../src/pages/ApiKeySettingsPage.tsx", import.meta.url), "utf8");
const onboarding = readFileSync(new URL("../src/components/product/brandKitOnboardingState.ts", import.meta.url), "utf8");

assert.match(authApi, /\/auth\/register/);
assert.match(context, /registrationEnabled/);
assert.match(login, /注册并创建独立工作区/);
assert.match(credentialApi, /\/credentials\/dashscope/);
assert.match(credentialApi, /api_key: apiKey/);
assert.match(credentialApi, /provider_workspace_id/);
assert.match(credentialApi, /region/);
assert.match(credentialApi, /\/credentials\/dashscope\/verify/);
assert.match(settings, /type="password"/);
assert.match(settings, /页面不会再次显示完整内容/);
assert.match(settings, /只有验证通过的 Key/);
assert.match(settings, /百炼业务空间 ID/);
assert.match(settings, /华北2（北京）/);
assert.match(onboarding, /API Key 设置/);
assert.doesNotMatch(onboarding, /QWEN_API_KEY/);
assert.doesNotMatch(settings, /localStorage|sessionStorage/);
assert.doesNotMatch(credentialApi, /localStorage|sessionStorage/);

console.log("Product auth frontend checks passed: 18 assertions.");
