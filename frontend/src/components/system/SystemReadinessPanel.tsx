import { useCallback, useEffect, useState } from "react";

import { getSystemReadiness } from "../../api/health";
import type { SystemReadinessResponse } from "../../types/health";

type LoadState = "loading" | "ready" | "failed";
type ComponentKey =
  | "backend"
  | "qwen"
  | "wanx"
  | "google_youtube"
  | "database"
  | "artifact_storage"
  | "execution_worker";

const COMPONENTS: Array<{ key: ComponentKey; label: string }> = [
  { key: "backend", label: "Backend" },
  { key: "qwen", label: "Qwen" },
  { key: "wanx", label: "Wanx" },
  { key: "google_youtube", label: "Google / YouTube" },
  { key: "database", label: "Database" },
  { key: "artifact_storage", label: "Artifact Storage" },
  { key: "execution_worker", label: "Execution Worker" },
];

export function SystemReadinessPanel() {
  const [state, setState] = useState<LoadState>("loading");
  const [readiness, setReadiness] = useState<SystemReadinessResponse | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    setState("loading");
    void getSystemReadiness(signal)
      .then((result) => {
        if (signal?.aborted) return;
        setReadiness(result);
        setState("ready");
      })
      .catch(() => {
        if (signal?.aborted) return;
        setReadiness(null);
        setState("failed");
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <section className="system-readiness" aria-label="系统就绪状态">
      <header>
        <div>
          <strong>系统就绪状态</strong>
          <span>仅检查本机配置，不调用Provider</span>
        </div>
        <button type="button" onClick={() => load()} disabled={state === "loading"}>
          {state === "loading" ? "检查中…" : "重新检查"}
        </button>
      </header>
      {state === "failed" ? (
        <p className="system-readiness__offline">
          Backend未连接。请运行start-socialpilotai.cmd；若仍失败，请查看本机Runtime日志。
        </p>
      ) : (
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
                      Revision: {readiness.database.revision_status}
                      {readiness.database.revision
                        ? ` · ${readiness.database.revision}`
                        : ""}
                    </small>
                  )}
                  {item && <p>{item.message}</p>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
