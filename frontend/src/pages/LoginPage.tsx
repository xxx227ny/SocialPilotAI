import axios from "axios";
import { type FormEvent, useState } from "react";

import { useAuth } from "../context/AuthContext";

export function LoginPage() {
  const { error: serviceError, login, register, registrationEnabled } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      if (mode === "register") {
        await register(username, password, workspaceName);
      } else {
        await login(username, password);
      }
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        setMessage("账号或密码不正确，请重新输入。");
      } else if (axios.isAxiosError(error) && error.response?.status === 409) {
        setMessage(error.response.data?.detail || "该邮箱已注册，请直接登录。");
      } else if (axios.isAxiosError(error) && error.response?.status === 422) {
        setMessage("请填写有效邮箱，密码至少需要 10 位。");
      } else {
        setMessage("登录服务暂时不可用，请稍后重试。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand" aria-hidden="true">S</div>
        <p className="login-eyebrow">SOCIALPILOT AI</p>
        <h1 id="login-title">登录营销工作台</h1>
        <p className="login-intro">
          {registrationEnabled
            ? "登录你的独立工作区，商品、任务和 API Key 均与其他用户隔离。"
            : "使用主办方评审账号体验短视频生产、社媒文案矩阵和投流优化闭环。"}
        </p>
        {registrationEnabled && (
          <div className="login-tabs" role="tablist" aria-label="账号操作">
            <button
              type="button"
              className={mode === "login" ? "is-active" : ""}
              onClick={() => { setMode("login"); setMessage(null); }}
            >登录</button>
            <button
              type="button"
              className={mode === "register" ? "is-active" : ""}
              onClick={() => { setMode("register"); setMessage(null); }}
            >注册</button>
          </div>
        )}
        <form onSubmit={submit}>
          <label>
            {registrationEnabled ? "邮箱" : "账号"}
            <input
              name="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder={registrationEnabled ? "请输入邮箱" : "请输入测试账号"}
              required
              autoFocus
            />
          </label>
          {mode === "register" && (
            <label>
              工作区名称（选填）
              <input
                name="workspaceName"
                type="text"
                autoComplete="organization"
                value={workspaceName}
                onChange={(event) => setWorkspaceName(event.target.value)}
                placeholder="例如：我的品牌工作区"
                minLength={2}
                maxLength={120}
              />
            </label>
          )}
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
              required
            />
          </label>
          {(message || serviceError) && (
            <p className="login-error" role="alert">{message || serviceError}</p>
          )}
          <button type="submit" disabled={submitting}>
            {submitting
              ? mode === "register" ? "正在注册…" : "正在登录…"
              : mode === "register" ? "注册并创建独立工作区" : "登录并进入工作台"}
          </button>
        </form>
        <p className="login-note">
          {registrationEnabled
            ? "注册后请前往“API Key 设置”，绑定你自己的阿里云百炼 Key。"
            : "测试账号由项目管理员配置，不开放公开注册。"}
        </p>
      </section>
    </main>
  );
}
