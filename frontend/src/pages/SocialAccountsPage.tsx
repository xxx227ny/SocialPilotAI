import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  disconnectWorkspaceSocialAccount,
  listWorkspaceSocialAccounts,
} from "../api/social";
import type { WorkspaceSocialAccount } from "../types/social";

const platformNames: Record<WorkspaceSocialAccount["platform"], string> = {
  youtube: "YouTube",
  instagram: "Instagram",
  tiktok: "TikTok",
  pinterest: "Pinterest",
};

const statusNames: Record<WorkspaceSocialAccount["connection_status"], string> = {
  CONNECTED: "已连接",
  DISCONNECTED: "已解除",
  EXPIRED: "授权已过期",
  FAILED: "连接异常",
};

function formatTime(value: string | null) {
  if (!value) return "未提供";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function SocialAccountsPage() {
  const [accounts, setAccounts] = useState<WorkspaceSocialAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setReadError(null);
    try {
      setAccounts(await listWorkspaceSocialAccounts());
    } catch {
      setReadError("暂时无法读取社媒账号，请检查网络后重试。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const connectedCount = useMemo(
    () => accounts.filter((account) => account.connection_status === "CONNECTED").length,
    [accounts],
  );

  const disconnect = async (account: WorkspaceSocialAccount) => {
    const confirmed = window.confirm(
      `确定解除 ${platformNames[account.platform]} 账号“${account.display_name}”吗？\n\n这只会删除 SocialPilot 保存的授权信息，不会删除或停用你的平台账号。`,
    );
    if (!confirmed) return;
    setWorkingId(account.id);
    setMessage(null);
    try {
      const updated = await disconnectWorkspaceSocialAccount(account.id);
      setAccounts((current) => current.map((item) => (
        item.id === updated.id ? updated : item
      )));
      setMessage(`${platformNames[account.platform]} 账号已从 SocialPilot 安全解除。`);
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
      setMessage(detail || "解除绑定失败，请稍后重试。");
    } finally {
      setWorkingId(null);
    }
  };

  return (
    <section className="settings-page social-account-center" aria-labelledby="social-accounts-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">账号与发布</span>
          <h1 id="social-accounts-title">社媒账号中心</h1>
          <p>集中查看当前工作区绑定的平台账号、所属商品与授权状态。</p>
        </div>
      </header>

      <article className="settings-card">
        <div className="social-account-summary">
          <div><strong>{loading ? "—" : accounts.length}</strong><span>全部记录</span></div>
          <div><strong>{loading ? "—" : connectedCount}</strong><span>正在连接</span></div>
          <div><strong>{loading ? "—" : new Set(accounts.map((item) => item.platform)).size}</strong><span>已接入平台</span></div>
        </div>

        <div className="settings-actions">
          <Link className="settings-link-button" to="/products">前往商品中心绑定新账号</Link>
          <button type="button" className="button-secondary" onClick={() => void load()} disabled={loading}>刷新状态</button>
        </div>

        {readError && <p className="settings-error" role="alert">{readError}</p>}
        {message && <p className="settings-message" role="status">{message}</p>}
        {loading && <p className="social-account-center__empty">正在读取当前工作区的社媒账号…</p>}
        {!loading && !readError && accounts.length === 0 && (
          <div className="social-account-center__empty">
            <strong>尚未绑定社媒账号</strong>
            <p>目前授权按商品管理。先在商品中心选择一个商品，再连接你自己的平台账号。</p>
          </div>
        )}
        {!loading && accounts.length > 0 && (
          <div className="social-account-center__list">
            {accounts.map((account) => (
              <section className="social-account-center__item" key={account.id}>
                <div className={`social-platform-mark is-${account.platform}`} aria-hidden="true">
                  {platformNames[account.platform].slice(0, 1)}
                </div>
                <div className="social-account-center__identity">
                  <div>
                    <span>{platformNames[account.platform]}</span>
                    <strong>{account.display_name}</strong>
                  </div>
                  <dl>
                    <div><dt>关联商品</dt><dd>{account.product_name}</dd></div>
                    <div><dt>平台账号标识</dt><dd>{account.provider_account_id}</dd></div>
                    <div><dt>授权到期</dt><dd>{formatTime(account.token_expires_at)}</dd></div>
                  </dl>
                </div>
                <div className="social-account-center__control">
                  <span className={`connection-badge is-${account.connection_status.toLowerCase()}`}>
                    {statusNames[account.connection_status]}
                  </span>
                  {account.connection_status !== "DISCONNECTED" && (
                    <button
                      type="button"
                      className="button-danger"
                      disabled={workingId === account.id}
                      onClick={() => void disconnect(account)}
                    >
                      {workingId === account.id ? "正在解除…" : "解除本系统绑定"}
                    </button>
                  )}
                </div>
              </section>
            ))}
          </div>
        )}

        <p className="settings-security-note">
          安全说明：本页面不会返回或展示平台访问令牌。解除绑定只清除 SocialPilot 内保存的授权信息，不会删除平台账号；如需彻底撤销授权，请前往对应平台的账号安全设置操作。
        </p>
      </article>
    </section>
  );
}
