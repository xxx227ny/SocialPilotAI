import axios from "axios";
import { type FormEvent, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  completeEmailVerification,
  completePasswordReset,
  requestPasswordReset,
} from "../api/auth";
import { useAuth } from "../context/AuthContext";

type LoginMode = "login" | "register" | "forgot" | "reset" | "verify";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    authenticated,
    error: serviceError,
    login,
    refresh,
    register,
    registrationEnabled,
  } = useAuth();
  const action = useMemo(
    () => new URLSearchParams(location.search).get("action"),
    [location.search],
  );
  const actionToken = useMemo(
    () => new URLSearchParams(location.search).get("token") || "",
    [location.search],
  );
  const initialMode: LoginMode = action === "reset-password"
    ? "reset"
    : action === "verify-email"
      ? "verify"
      : "login";
  const [mode, setMode] = useState<LoginMode>(initialMode);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const selectMode = (nextMode: LoginMode) => {
    setMode(nextMode);
    setMessage(null);
    setSuccess(false);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    setSuccess(false);
    try {
      if (mode === "register") {
        await register(username, password, workspaceName);
        navigate("/settings/api-key", { replace: true });
      } else if (mode === "forgot") {
        const result = await requestPasswordReset(username);
        setMessage(result.message);
        setSuccess(true);
      } else if (mode === "reset") {
        if (!actionToken) {
          setMessage("重置链接缺少安全令牌，请重新申请。");
          return;
        }
        if (password !== confirmation) {
          setMessage("两次输入的新密码不一致。");
          return;
        }
        const result = await completePasswordReset(actionToken, password);
        await refresh();
        setMessage(result.message);
        setSuccess(true);
      } else if (mode === "verify") {
        if (!actionToken) {
          setMessage("验证链接缺少安全令牌，请重新申请。");
          return;
        }
        const result = await completeEmailVerification(actionToken);
        await refresh();
        setMessage(result.message);
        setSuccess(true);
      } else {
        await login(username, password);
      }
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        setMessage("账号或密码不正确，请重新输入。");
      } else if (axios.isAxiosError(error) && error.response?.status === 409) {
        setMessage(error.response.data?.detail || "该邮箱已注册，请直接登录。");
      } else if (axios.isAxiosError(error) && error.response?.status === 400) {
        setMessage(error.response.data?.detail || "链接无效或已过期。");
      } else if (axios.isAxiosError(error) && error.response?.status === 422) {
        setMessage(
          error.response.data?.detail || "请检查输入内容，密码至少需要 10 位。",
        );
      } else {
        setMessage("登录服务暂时不可用，请稍后重试。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const finishAction = () => {
    navigate("/", { replace: true });
    selectMode("login");
  };

  const title = mode === "forgot"
    ? "找回密码"
    : mode === "reset"
      ? "设置新密码"
      : mode === "verify"
        ? "验证邮箱"
        : "登录营销工作台";

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand" aria-hidden="true">S</div>
        <p className="login-eyebrow">SOCIALPILOT AI</p>
        <h1 id="login-title">{title}</h1>
        <p className="login-intro">
          {mode === "forgot"
            ? "输入注册邮箱。为保护账号，无论邮箱是否存在，系统都会返回相同结果。"
            : mode === "reset"
              ? "重置成功后，所有设备上的旧登录都会立即失效。"
              : mode === "verify"
                ? "确认验证后，邮箱将与当前 SocialPilot AI 账号绑定。"
                : registrationEnabled
                  ? "登录你的独立工作区，商品、任务和 API Key 均与其他用户隔离。"
                  : "使用主办方评审账号体验短视频生产、社媒文案矩阵和投流优化闭环。"}
        </p>
        {registrationEnabled && ["login", "register"].includes(mode) && (
          <div className="login-tabs" role="tablist" aria-label="账号操作">
            <button
              type="button"
              className={mode === "login" ? "is-active" : ""}
              onClick={() => selectMode("login")}
            >登录</button>
            <button
              type="button"
              className={mode === "register" ? "is-active" : ""}
              onClick={() => selectMode("register")}
            >注册</button>
          </div>
        )}
        <form onSubmit={submit}>
          {["login", "register", "forgot"].includes(mode) && (
            <label>
              {registrationEnabled ? "邮箱" : "账号"}
              <input
                name="username"
                type={registrationEnabled ? "email" : "text"}
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={registrationEnabled ? "请输入邮箱" : "请输入测试账号"}
                required
                autoFocus
              />
            </label>
          )}
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
          {mode === "login" && (
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
          )}
          {["register", "reset"].includes(mode) && (
            <label>
              {mode === "reset" ? "新密码" : "密码"}
              <input
                name="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={mode === "reset" ? "至少 10 位" : "请输入密码"}
                minLength={10}
                required
              />
            </label>
          )}
          {mode === "reset" && (
            <label>
              再次输入新密码
              <input
                name="confirmation"
                type="password"
                autoComplete="new-password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                minLength={10}
                required
              />
            </label>
          )}
          {(message || serviceError) && (
            <p className={success ? "login-success" : "login-error"} role="status">
              {message || serviceError}
            </p>
          )}
          {success && ["reset", "verify"].includes(mode) ? (
            <button type="button" onClick={finishAction}>
              {authenticated && mode === "verify" ? "返回工作台" : "返回登录"}
            </button>
          ) : (
            <button type="submit" disabled={submitting}>
              {submitting
                ? "正在处理…"
                : mode === "register"
                  ? "注册并创建独立工作区"
                  : mode === "forgot"
                    ? "发送重置链接"
                    : mode === "reset"
                      ? "确认重置密码"
                      : mode === "verify"
                        ? "确认验证邮箱"
                        : "登录并进入工作台"}
            </button>
          )}
        </form>
        {registrationEnabled && mode === "login" && (
          <button
            type="button"
            className="login-link-button"
            onClick={() => selectMode("forgot")}
          >忘记密码？</button>
        )}
        {["forgot", "reset", "verify"].includes(mode) && (
          <button type="button" className="login-link-button" onClick={finishAction}>
            返回登录
          </button>
        )}
        <p className="login-note">
          {mode === "forgot"
            ? "若未收到邮件，请检查垃圾箱；邮件服务尚未配置时请联系管理员。"
            : registrationEnabled
              ? "注册成功后将直接进入 API Key 设置，完成绑定后再创建商品。"
              : "测试账号由项目管理员配置，不开放公开注册。"}
        </p>
      </section>
    </main>
  );
}
