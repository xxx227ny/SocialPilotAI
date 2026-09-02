import axios from "axios";
import { type FormEvent, useState } from "react";

import { changePassword, revokeOtherSessions } from "../api/auth";

export function AccountSecurityPage() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    setError(null);
    if (newPassword !== confirmation) {
      setError("两次输入的新密码不一致。");
      return;
    }
    if (newPassword === currentPassword) {
      setError("新密码不能与当前密码相同。");
      return;
    }
    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setMessage("密码已更新，其他设备上的登录已全部退出。");
    } catch (caught) {
      if (axios.isAxiosError(caught) && caught.response?.status === 401) {
        setError("当前密码不正确。");
      } else if (axios.isAxiosError(caught) && caught.response?.status === 422) {
        setError(caught.response.data?.detail || "新密码不符合安全要求。");
      } else {
        setError("密码更新失败，请稍后重试。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const revokeOthers = async () => {
    setMessage(null);
    setError(null);
    setRevoking(true);
    try {
      const result = await revokeOtherSessions();
      setMessage(
        result.revoked_sessions > 0
          ? `已退出其他设备上的 ${result.revoked_sessions} 个登录。`
          : "当前没有其他设备处于登录状态。",
      );
    } catch {
      setError("无法退出其他设备，请稍后重试。");
    } finally {
      setRevoking(false);
    }
  };

  return (
    <section className="settings-page" aria-labelledby="account-security-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">账号与安全</span>
          <h1 id="account-security-title">账号安全</h1>
          <p>修改密码会更换当前登录凭证，并立即退出其他设备。</p>
        </div>
      </header>

      <article className="settings-card">
        <div className="credential-status">
          <span className="status-dot is-ready" />
          <div>
            <strong>登录保护已启用</strong>
            <p>连续输错密码会被临时限制，降低账号被暴力尝试的风险。</p>
          </div>
        </div>

        <form onSubmit={submit} className="credential-form">
          <label>
            当前密码
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </label>
          <label>
            新密码
            <input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              minLength={10}
              maxLength={256}
              required
            />
            <small>至少 10 位，请勿与当前密码相同。</small>
          </label>
          <label>
            再次输入新密码
            <input
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              minLength={10}
              maxLength={256}
              required
            />
          </label>
          <div className="settings-actions">
            <button type="submit" disabled={submitting || revoking}>
              {submitting ? "正在更新…" : "更新密码"}
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={submitting || revoking}
              onClick={revokeOthers}
            >
              {revoking ? "正在处理…" : "退出其他设备"}
            </button>
          </div>
        </form>
        {message && <p className="settings-message" role="status">{message}</p>}
        {error && <p className="settings-error" role="alert">{error}</p>}
        <p className="settings-security-note">
          密码仅以不可逆摘要保存；退出其他设备不会删除商品、API Key 或任务数据。
        </p>
      </article>
    </section>
  );
}
