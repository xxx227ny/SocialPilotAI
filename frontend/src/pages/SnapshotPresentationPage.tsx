import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { loadPresentationSnapshotOnce } from "../api/presentationSnapshots";
import { SnapshotCopySlide } from "../components/presentation/SnapshotCopySlide";
import { SnapshotGrowthSlide } from "../components/presentation/SnapshotGrowthSlide";
import { SnapshotOverviewSlide } from "../components/presentation/SnapshotOverviewSlide";
import { SnapshotVideoSlide } from "../components/presentation/SnapshotVideoSlide";
import {
  readSnapshotPresentationView,
} from "../components/presentation/snapshotPresentationPayload";
import type { SnapshotPresentationRoute } from "../components/presentation/snapshotPresentationState";
import type { PresentationSnapshot } from "../types/presentationSnapshot";

const SLIDES = [
  { pathname: "/", number: "01", label: "Overview" },
  { pathname: "/copy-matrix", number: "02", label: "Copy Matrix" },
  { pathname: "/content-studio", number: "03", label: "Video Blueprint" },
  { pathname: "/growth-copilot", number: "04", label: "Growth Copilot" },
] as const;

export function SnapshotPresentationPage({
  route,
}: {
  route: Exclude<SnapshotPresentationRoute, { kind: "legacy" }>;
}) {
  const location = useLocation();
  const snapshotId = route.kind === "snapshot" ? route.snapshotId : null;
  const [snapshot, setSnapshot] = useState<PresentationSnapshot | null>(null);
  const routeError = route.kind === "invalid" ? route.message : "";
  const [loading, setLoading] = useState(snapshotId !== null);
  const [error, setError] = useState(routeError);

  useEffect(() => {
    if (snapshotId === null) {
      setLoading(false);
      setSnapshot(null);
      setError(routeError);
      return;
    }
    let active = true;
    setLoading(true);
    setSnapshot(null);
    setError("");
    void loadPresentationSnapshotOnce(snapshotId)
      .then((result) => {
        if (!active) return;
        if (result.id !== snapshotId) {
          throw new Error("Snapshot identity mismatch");
        }
        setSnapshot(result);
      })
      .catch(() => {
        if (active) {
          setError("无法加载指定的演示快照；不会回退到其他快照或最新数据。");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [routeError, snapshotId]);

  const view = useMemo(
    () => snapshot ? readSnapshotPresentationView(snapshot) : null,
    [snapshot],
  );
  const currentSlide = SLIDES.find(
    (slide) => slide.pathname === location.pathname,
  );

  return (
    <div className="snapshot-presentation-shell">
      <header className="snapshot-presentation-header">
        <div>
          <span>SocialPilot AI · Immutable Presentation Snapshot</span>
          <h1>只读演示快照</h1>
          <p>四页内容仅来自URL指定的单一不可变Snapshot payload。</p>
        </div>
        <strong>0 AI Calls · 0 Provider Calls · Read Only</strong>
      </header>

      {snapshotId !== null ? (
        <nav className="snapshot-presentation-nav" aria-label="Snapshot Presentation">
          {SLIDES.map((slide) => (
            <Link
              className={slide.pathname === location.pathname ? "is-active" : ""}
              key={slide.pathname}
              to={{
                pathname: slide.pathname,
                search: `?mode=presentation&snapshot_id=${snapshotId}`,
              }}
            >
              <span>{slide.number}</span>
              <strong>{slide.label}</strong>
            </Link>
          ))}
        </nav>
      ) : null}

      {snapshot ? <SnapshotIdentity snapshot={snapshot} /> : null}

      {loading ? (
        <SnapshotState title="正在读取指定快照" detail="仅请求一次精确Snapshot GET。" />
      ) : error || !snapshot || !view ? (
        <SnapshotState error title="无法进入快照演示" detail={error || "未提供可验证的Snapshot。"} />
      ) : !currentSlide ? (
        <SnapshotState error title="未知演示页面" detail="当前路径不属于该Snapshot的四页只读演示；不会回退到其他页面数据。" />
      ) : (
        <main className="snapshot-presentation-stage">
          {currentSlide.pathname === "/" ? <SnapshotOverviewSlide snapshot={snapshot} view={view} /> : null}
          {currentSlide.pathname === "/copy-matrix" ? (
            <SnapshotCopySlide
              copies={view.copies}
              strategyId={view.strategy?.id ?? null}
              copyMatrixId={view.copyMatrixId}
            />
          ) : null}
          {currentSlide.pathname === "/content-studio" ? <SnapshotVideoSlide snapshot={snapshot} view={view} /> : null}
          {currentSlide.pathname === "/growth-copilot" ? <SnapshotGrowthSlide view={view} /> : null}
        </main>
      )}
    </div>
  );
}

function SnapshotIdentity({ snapshot }: { snapshot: PresentationSnapshot }) {
  const included = [
    ["Product", true],
    ["Brief", !snapshot.missing_sections.includes("marketing_brief")],
    ["Strategy", !snapshot.missing_sections.includes("marketing_strategy")],
    ["Copy", !snapshot.missing_sections.includes("copy_matrix")],
    ["Video", !snapshot.missing_sections.includes("video_project")],
    ["Render", !snapshot.missing_sections.includes("render_task")],
    ["Artifact", !snapshot.missing_sections.includes("artifact")],
    ["Delivery", !snapshot.missing_sections.includes("publish_task")],
    ["Campaigns", !snapshot.missing_sections.includes("campaigns")],
  ] as const;
  return (
    <section className="snapshot-presentation-identity">
      <div><small>Snapshot</small><strong>#{snapshot.id}</strong></div>
      <div><small>Digest</small><code>{digestSummary(snapshot.digest)}</code></div>
      <div><small>创建时间</small><strong>{formatDateTime(snapshot.created_at)}</strong></div>
      <div><small>Schema</small><strong>v{snapshot.schema_version}</strong></div>
      <div className="snapshot-presentation-identity__coverage">
        {included.map(([label, available]) => (
          <span className={available ? "is-present" : "is-missing"} key={label}>
            {label} · {available ? "包含" : "缺失"}
          </span>
        ))}
      </div>
    </section>
  );
}

function SnapshotState({ title, detail, error = false }: { title: string; detail: string; error?: boolean }) {
  return <main><section className={`snapshot-presentation-state${error ? " snapshot-presentation-state--error" : ""}`}><strong>{title}</strong><p>{detail}</p></section></main>;
}

function digestSummary(digest: string): string {
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间未知"
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
