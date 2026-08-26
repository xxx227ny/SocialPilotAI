import axios from "axios";
import { type FormEvent, useState } from "react";

import { useAuth } from "../context/AuthContext";

export function LoginPage() {
  const { error: serviceError, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      await login(username, password);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        setMessage("账号或密码不正确，请重新输入。");
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
          使用主办方评审账号体验短视频生产、社媒文案矩阵和投流优化闭环。
        </p>
        <form onSubmit={submit}>
          <label>
            账号
            <input
              name="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入测试账号"
              required
              autoFocus
            />
          </label>
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
            {submitting ? "正在登录…" : "登录并进入工作台"}
          </button>
        </form>
        <p className="login-note">测试账号由项目管理员配置，不开放公开注册。</p>
      </section>
    </main>
  );
}
