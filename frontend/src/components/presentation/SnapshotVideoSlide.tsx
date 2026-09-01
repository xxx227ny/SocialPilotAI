import { getPresentationSnapshotArtifactPreviewUrl } from "../../api/presentationSnapshots";
import type { PresentationSnapshot } from "../../types/presentationSnapshot";
import type { SnapshotPresentationView } from "./snapshotPresentationPayload";

export function SnapshotVideoSlide({
  snapshot,
  view,
}: {
  snapshot: PresentationSnapshot;
  view: SnapshotPresentationView;
}) {
  const video = view.video;
  const artifactAvailable = Boolean(
    view.artifact
      && snapshot.artifact_snapshot_path
      && snapshot.artifact_sha256,
  );

  return (
    <div className="snapshot-slide snapshot-video-slide">
      <header className="snapshot-slide-title">
        <div><span>03 · VIDEO BLUEPRINT</span><h2>{video?.title || "VideoProject缺失"}</h2></div>
        <dl>
          <Fact label="平台" value={video?.platform} />
          <Fact label="时长" value={video?.durationSeconds == null ? "" : `${video.durationSeconds}秒`} />
          <Fact label="画幅" value={video?.aspectRatio} />
          <Fact label="状态" value={video?.status} />
        </dl>
      </header>

      <section className="snapshot-video-layout">
        <article className="snapshot-storyboard">
          <header><span>STORYBOARD</span><strong>{video ? `VideoProject #${video.id}` : "缺失"}</strong></header>
          {video?.concept ? <blockquote>{video.concept}</blockquote> : null}
          {video && video.scenes.length > 0 ? (
            <div>
              {video.scenes.map((scene, index) => (
                <section key={`${scene.sequence ?? index}-${index}`}>
                  <aside><small>SCENE</small><strong>{String(scene.sequence ?? index + 1).padStart(2, "0")}</strong><span>{scene.durationSeconds == null ? "时长缺失" : `${scene.durationSeconds}s`}</span></aside>
                  <div>
                    <small>{scene.shotType || "SHOT TYPE缺失"}</small>
                    <h3>{scene.visualDescription || "视觉描述缺失"}</h3>
                    <p>{scene.action || "动作字段缺失"}</p>
                    {scene.narration ? <blockquote>“{scene.narration}”</blockquote> : null}
                  </div>
                </section>
              ))}
            </div>
          ) : <Empty text="Snapshot没有VideoProject场景/分镜。" />}
          {video?.cta ? <footer><span>CTA</span><strong>{video.cta}</strong></footer> : null}
        </article>

        <aside className="snapshot-video-evidence">
          <article className="snapshot-render-card">
            <header><span>RENDER TASK</span><strong>{view.render ? `#${view.render.id}` : "缺失"}</strong></header>
            {view.render ? (
              <dl>
                <Fact label="状态" value={view.render.status} />
                <Fact label="Provider记录" value={view.render.providerName} />
                <Fact label="分辨率" value={view.render.resolution} />
                <Fact label="时长" value={view.render.durationSeconds == null ? "" : `${view.render.durationSeconds}秒`} />
                <Fact label="画幅" value={view.render.aspectRatio} />
              </dl>
            ) : <Empty text="Snapshot未包含RenderTask。" />}
          </article>

          <article className="snapshot-artifact-card">
            <header><span>SNAPSHOT ARTIFACT</span><strong>{view.artifact ? `#${view.artifact.id}` : "缺失"}</strong></header>
            {artifactAvailable && view.artifact ? (
              <>
                <video controls playsInline preload="metadata" src={getPresentationSnapshotArtifactPreviewUrl(snapshot.id)}>
                  Your browser does not support video playback.
                </video>
                <dl>
                  <Fact label="RenderTask" value={view.artifact.renderTaskId == null ? "" : `#${view.artifact.renderTaskId}`} />
                  <Fact label="类型" value={view.artifact.contentType} />
                  <Fact label="大小" value={formatBytes(view.artifact.sizeBytes)} />
                  <Fact label="SHA-256" value={hashSummary(view.artifact.sha256)} />
                </dl>
              </>
            ) : <Empty text="Snapshot未包含可验证的独立Artifact副本。" />}
          </article>

          <article className="snapshot-delivery-card">
            <header><span>DELIVERY EVIDENCE</span><strong>{view.publish ? `PublishTask #${view.publish.id}` : "缺失"}</strong></header>
            {view.publish ? (
              <dl>
                <Fact label="平台" value={view.publish.platform} />
                <Fact label="隐私" value={view.publish.privacyStatus} />
                <Fact label="状态" value={view.publish.status} />
                <Fact label="完成时间" value={formatDateTime(view.publish.completedAt)} />
                <Fact label="Artifact" value={view.publish.artifactId == null ? "" : `#${view.publish.artifactId}`} />
              </dl>
            ) : <Empty text="Snapshot未包含PublishTask，不显示其他交付记录。" />}
            <p>本卡片仅展示本地不可变交付证据，不提供外部链接或发布操作。</p>
          </article>
        </aside>
      </section>
    </div>
  );
}

function Fact({ label, value }: { label: string; value?: string }) {
  return <div><dt>{label}</dt><dd>{value || "缺失"}</dd></div>;
}

function Empty({ text }: { text: string }) {
  return <div className="snapshot-empty-evidence"><strong>数据缺失</strong><p>{text}</p></div>;
}

function hashSummary(value: string): string {
  return value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-12)}` : value || "缺失";
}

function formatBytes(value: number | null): string {
  return value == null ? "缺失" : `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime())
    ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date)
    : "缺失";
}
