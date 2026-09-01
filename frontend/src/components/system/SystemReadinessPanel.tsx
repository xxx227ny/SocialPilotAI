import { useState } from "react";
import { useReadResource } from "../../hooks/useReadResource";

import { getSystemReadiness } from "../../api/health";
import type { SystemReadinessResponse } from "../../types/health";

type LoadState = "loading" | "ready" | "failed";
type ComponentKey =
  | "backend"
  | "qwen"
  | "wanx"
  | "google_youtube"
  | "meta_instagram"
  | "tiktok"
  | "pinterest"
  | "tiktok_publishing"
  | "instagram_publishing"
  | "database"
  | "artifact_storage"
  | "execution_worker";

const COMPONENTS: Array<{ key: ComponentKey; label: string }> = [
  { key: "backend", label: "后端服务" },
  { key: "qwen", label: "千问" },
  { key: "wanx", label: "万象" },
  { key: "google_youtube", label: "谷歌 / YouTube" },
  { key: "meta_instagram", label: "Meta / Instagram" },
  { key: "tiktok", label: "TikTok 账号连接" },
  { key: "pinterest", label: "Pinterest 账号连接" },
  { key: "tiktok_publishing", label: "TikTok 视频发布" },
  { key: "instagram_publishing", label: "Instagram 短视频发布" },
  { key: "database", label: "数据库" },
  { key: "artifact_storage", label: "文件存储" },
  { key: "execution_worker", label: "后台执行器" },
];

export function SystemReadinessPanel() {
  const read = useReadResource("system-readiness", getSystemReadiness);
  const readiness = read.data;
  // A transient refresh failure must not replace a previously verified snapshot
  // with an alarming whole-system outage. The timestamp below makes staleness clear.
  const state: LoadState = readiness
    ? "ready"
    : read.loading
      ? "loading"
      : read.error
        ? "failed"
        : "ready";
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="system-readiness" aria-label="系统就绪状态">
      <header>
        <div>
          <strong>系统就绪状态</strong>
          <span>{coreReadinessLabel(readiness, state)}</span>
          {read.loadedAt !== null && <small>检查于 {new Date(read.loadedAt).toLocaleTimeString("zh-CN")}；配置就绪不代表公网始终连通</small>}
        </div>
        <div className="system-readiness__actions">
          <button type="button" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起详情" : "展开详情"}
          </button>
          {expanded ? (
            <button type="button" onClick={read.refresh} disabled={state === "loading"}>
              {state === "loading" ? "检查中……" : "重新检查"}
            </button>
          ) : null}
        </div>
      </header>
      {expanded && read.error && readiness ? (
        <p className="system-readiness__offline" role="status">
          本次刷新暂时失败；继续显示上次成功检查的结果，业务数据不会因此被清空。可稍后重新检查。
        </p>
      ) : null}
      {expanded && state === "failed" ? (
        <p className="system-readiness__offline">
          暂时无法确认最新系统状态，可能是公网连接中断或超时，不代表 API Key 缺失。请重新检查；若持续失败，请检查本机后台和公网通道。
        </p>
      ) : expanded ? (
        <div className="system-readiness__grid">
          {COMPONENTS.map((component) => {
            const item = readiness?.[component.key];
            const ready = item?.ready === true;
            return (
              <article
                className={`system-readiness__item${ready ? " is-ready" : " is-missing"}`}
                key={component.key}
              >
                <span aria-hidden="true" />
                <div>
                  <strong>{component.label}</strong>
                  <small>{item ? (ready ? "已就绪" : "需要配置") : "检查中"}</small>
                  {component.key === "database" && readiness?.database && (
                    <small>
                      版本状态：{readiness.database.revision_status}
                      {readiness.database.revision
                        ? ` · ${readiness.database.revision}`
                        : ""}
                    </small>
                  )}
                  {item && (
                    <p>{ready ? "配置检查已通过。" : "尚未配置；对应的可选功能不会启用。"}</p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function coreReadinessLabel(
  readiness: SystemReadinessResponse | null,
  state: LoadState,
) {
  if (state === "loading") return "正在检查本机配置，不调用模型";
  if (state === "failed" || !readiness) return "连接异常，最新状态待确认";
  const coreReady = [
    readiness.backend,
    readiness.qwen,
    readiness.wanx,
    readiness.database,
    readiness.artifact_storage,
    readiness.execution_worker,
  ].every((item) => item.ready);
  return coreReady ? "上次检查：核心生成服务已就绪" : "上次检查：部分核心服务需要配置";
}
