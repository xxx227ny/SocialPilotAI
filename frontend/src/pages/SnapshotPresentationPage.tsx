import { useEffect, useMemo, useState } from "react";

import {
  getPresentationSnapshot,
  getPresentationSnapshotArtifactContentUrl,
} from "../api/presentationSnapshots";
import type { SnapshotPresentationRoute } from "../components/presentation/snapshotPresentationState";
import type {
  PresentationSnapshot,
  PresentationSnapshotSection,
} from "../types/presentationSnapshot";

const SECTION_LABELS: Record<PresentationSnapshotSection, string> = {
  marketing_brief: "MarketingBrief",
  marketing_strategy: "Strategy",
  copy_matrix: "CopyMatrix",
  video_project: "VideoProject",
  render_task: "RenderTask",
  artifact: "Artifact",
  publish_task: "PublishTask",
  campaigns: "Campaigns",
};

export function SnapshotPresentationPage({
  route,
}: {
  route: Exclude<SnapshotPresentationRoute, { kind: "legacy" }>;
}) {
  const [snapshot, setSnapshot] = useState<PresentationSnapshot | null>(null);
  const [loading, setLoading] = useState(route.kind === "snapshot");
  const [error, setError] = useState(
    route.kind === "invalid" ? route.message : "",
  );

  useEffect(() => {
    if (route.kind !== "snapshot") return;
    const controller = new AbortController();
    setLoading(true);
    setSnapshot(null);
    setError("");
    void getPresentationSnapshot(route.snapshotId, controller.signal)
      .then((result) => {
        if (result.id !== route.snapshotId) {
          throw new Error("Snapshot identity mismatch");
        }
        setSnapshot(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError("无法加载指定的演示快照；不会回退到其他快照或最新数据。");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [route]);

  const sections = useMemo(() => {
    if (!snapshot) return { included: [], missing: [] };
    const keys = Object.keys(SECTION_LABELS) as PresentationSnapshotSection[];
    return {
      included: keys.filter(
        (section) => !snapshot.missing_sections.includes(section),
      ),
      missing: snapshot.missing_sections,
    };
  }, [snapshot]);

  return (
    <main className="snapshot-presentation-shell">
      <header className="snapshot-presentation-header">
        <div>
          <span>SocialPilot AI · Immutable Presentation Snapshot</span>
          <h1>只读演示快照</h1>
          <p>仅加载URL中指定的不可变快照，不读取latest或当前业务记录。</p>
        </div>
        <strong>0 AI Calls · 0 Provider Calls · Read Only</strong>
      </header>

      {loading ? (
        <SnapshotState title="正在读取指定快照" detail="只发起一次精确Snapshot GET。" />
      ) : error || !snapshot ? (
        <SnapshotState
          error
          title="无法进入快照演示"
          detail={error || "未提供可验证的Snapshot。"}
        />
      ) : (
        <>
          <section className="snapshot-presentation-summary">
            <div><small>Snapshot</small><strong>#{snapshot.id}</strong></div>
            <div><small>Digest</small><code>{digestSummary(snapshot.digest)}</code></div>
            <div><small>创建时间</small><strong>{formatDateTime(snapshot.created_at)}</strong></div>
            <div><small>Schema</small><strong>v{snapshot.schema_version}</strong></div>
          </section>

          <section className="snapshot-presentation-sections">
            <SnapshotSectionList
              title="包含项"
              values={sections.included.map((section) => SECTION_LABELS[section])}
            />
            <SnapshotSectionList
              title="缺失项"
              values={sections.missing.map((section) => SECTION_LABELS[section])}
            />
          </section>

          {snapshot.artifact_snapshot_path && snapshot.artifact_sha256 ? (
            <section className="snapshot-presentation-media">
              <div>
                <span>SNAPSHOT ARTIFACT</span>
                <h2>不可变媒体副本</h2>
                <p>播放前由后端校验安全路径、文件大小和SHA-256；不会读取原始可变Artifact代替。</p>
              </div>
              <video
                controls
                playsInline
                preload="metadata"
                src={getPresentationSnapshotArtifactContentUrl(snapshot.id)}
              >
                Your browser does not support video playback.
              </video>
            </section>
          ) : (
            <SnapshotState
              title="快照未包含媒体"
              detail="该快照如实记录Artifact缺失，不会回退到其他媒体。"
            />
          )}
        </>
      )}
    </main>
  );
}

function SnapshotSectionList({ title, values }: { title: string; values: string[] }) {
  return (
    <article>
      <h2>{title}</h2>
      <div>
        {values.length > 0
          ? values.map((value) => <span key={value}>{value}</span>)
          : <span>无</span>}
      </div>
    </article>
  );
}

function SnapshotState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return (
    <section className={`snapshot-presentation-state${error ? " snapshot-presentation-state--error" : ""}`}>
      <strong>{title}</strong>
      <p>{detail}</p>
    </section>
  );
}

function digestSummary(digest: string): string {
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间未知"
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}
