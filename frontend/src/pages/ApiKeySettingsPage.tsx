import axios from "axios";
import { type FormEvent, useEffect, useState } from "react";

import {
  deleteDashScopeCredential,
  getDashScopeCredential,
  saveDashScopeCredential,
} from "../api/credentials";
import type { ProviderCredential } from "../types/credentials";

export function ApiKeySettingsPage() {
  const [credential, setCredential] = useState<ProviderCredential | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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
    try {
      const saved = await saveDashScopeCredential(apiKey);
      setCredential(saved);
      setApiKey("");
      setMessage("API Key 已加密保存，并绑定到当前工作区。后续 AI 消耗由该 Key 承担。");
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
      setMessage(detail || "API Key 保存失败，请检查后重试。");
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
          <span className={`status-dot${credential?.configured ? " is-ready" : ""}`} />
          <div>
            <strong>{loading ? "正在读取…" : credential?.configured ? "已绑定" : "尚未绑定"}</strong>
            <p>{credential?.configured ? `当前 Key：${credential.key_hint}` : "绑定后才能生成文案、图片、语音和视频。"}</p>
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
              {submitting ? "正在保存…" : credential?.configured ? "替换 API Key" : "加密保存并绑定"}
            </button>
            {credential?.configured && (
              <button type="button" className="button-danger" onClick={remove} disabled={submitting}>删除绑定</button>
            )}
          </div>
        </form>
        {message && <p className="settings-message" role="status">{message}</p>}
        <p className="settings-security-note">安全说明：服务器只保存加密密文和末四位提示；接口响应、任务记录和日志均不返回完整 Key。</p>
      </article>
    </section>
  );
}
