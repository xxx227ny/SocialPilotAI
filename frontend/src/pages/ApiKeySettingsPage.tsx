import axios from "axios";
import { type FormEvent, useEffect, useState } from "react";

import {
  deleteDashScopeCredential,
  getDashScopeCredential,
  saveDashScopeCredential,
  verifyDashScopeCredential,
} from "../api/credentials";
import type { ProviderCredential } from "../types/credentials";

export function ApiKeySettingsPage() {
  const [credential, setCredential] = useState<ProviderCredential | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const verifySavedKey = async () => {
    setSubmitting(true);
    setMessage(null);
    try {
      const verification = await verifyDashScopeCredential();
      setCredential((current) => current ? {
        ...current,
        verified: verification.verified,
        verified_at: verification.verified_at,
      } : current);
      setMessage(verification.message);
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
      setMessage(detail || "API Key 验证服务暂时不可用，请稍后手动重试。");
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    getDashScopeCredential()
      .then(setCredential)
      .catch(() => setMessage("暂时无法读取 API Key 状态，请稍后重试。"))
      .finally(() => setLoading(false));
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    let saved: ProviderCredential;
    try {
      saved = await saveDashScopeCredential(apiKey);
      setCredential(saved);
      setApiKey("");
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
      setMessage(detail || "API Key 保存失败，请检查后重试。");
      setSubmitting(false);
      return;
    }
    try {
      const verification = await verifyDashScopeCredential();
      setCredential({
        ...saved,
        verified: verification.verified,
        verified_at: verification.verified_at,
      });
      setMessage(verification.message);
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
      setMessage(detail || "API Key 已加密保存，但在线验证未完成；AI 功能保持关闭，请稍后重新验证。");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("确定删除当前工作区绑定的 API Key 吗？删除后将无法生成 AI 内容。")) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await deleteDashScopeCredential();
      setCredential({
        provider: "DASHSCOPE",
        configured: false,
        key_hint: null,
        verified: false,
        verified_at: null,
        updated_at: null,
      });
      setMessage("API Key 已删除。AI 生成功能已停止调用。 ");
    } catch {
      setMessage("删除失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="settings-page" aria-labelledby="api-key-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">账号与费用</span>
          <h1 id="api-key-title">阿里云百炼 API Key</h1>
          <p>你的 Key 仅加密保存在当前工作区，页面不会再次显示完整内容。</p>
        </div>
      </header>

      <article className="settings-card">
        <div className="credential-status">
          <span className={`status-dot${credential?.verified ? " is-ready" : credential?.configured ? " is-pending" : ""}`} />
          <div>
            <strong>{loading ? "正在读取…" : credential?.verified ? "已验证并启用" : credential?.configured ? "已保存，尚未验证" : "尚未绑定"}</strong>
            <p>{credential?.configured ? `当前 Key：${credential.key_hint}${credential.verified ? "；AI 功能已启用。" : "；AI 功能保持关闭。"}` : "绑定并验证后才能生成文案、图片、语音和视频。"}</p>
          </div>
        </div>

        <form onSubmit={submit} className="credential-form">
          <label>
            {credential?.configured ? "输入新 Key 进行替换" : "输入你的百炼 API Key"}
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="sk-..."
              minLength={8}
              maxLength={512}
              required
            />
          </label>
          <div className="settings-actions">
            <button type="submit" disabled={submitting || apiKey.trim().length < 8}>
              {submitting ? "正在处理…" : credential?.configured ? "替换并验证 API Key" : "保存、验证并绑定"}
            </button>
            {credential?.configured && (
              <>
                <button type="button" className="button-secondary" onClick={verifySavedKey} disabled={submitting}>重新验证</button>
                <button type="button" className="button-danger" onClick={remove} disabled={submitting}>删除绑定</button>
              </>
            )}
          </div>
        </form>
        {message && <p className="settings-message" role="status">{message}</p>}
        <p className="settings-security-note">安全说明：验证只读取阿里云百炼模型列表，不生成内容；服务器只保存加密密文和末四位提示，接口响应、任务记录和日志均不返回完整 Key。只有验证通过的 Key 才能被 AI 任务使用。</p>
      </article>
    </section>
  );
}
