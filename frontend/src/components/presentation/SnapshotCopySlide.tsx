import {
  formatSnapshotCopyIdentity,
  type SnapshotCopyView,
} from "./snapshotPresentationPayload";

const PRIMARY_PLATFORMS = ["TikTok", "Instagram", "Facebook"];

export function SnapshotCopySlide({
  copies,
  strategyId,
  copyMatrixId,
}: {
  copies: SnapshotCopyView[];
  strategyId: number | null;
  copyMatrixId: number | null;
}) {
  const primary = PRIMARY_PLATFORMS.map((platform) => ({
    platform,
    copy: copies.find(
      (item) => item.platform.toLowerCase() === platform.toLowerCase(),
    ),
  }));
  const extras = copies.filter(
    (copy) => !PRIMARY_PLATFORMS.some(
      (platform) => platform.toLowerCase() === copy.platform.toLowerCase(),
    ),
  );

  return (
    <div className="snapshot-slide snapshot-copy-slide">
      <header className="snapshot-slide-title">
        <div><span>02 · COPY MATRIX</span><h2>平台文案矩阵</h2></div>
        <strong>{formatSnapshotCopyIdentity(strategyId, copyMatrixId)}</strong>
        <p>仅展示Snapshot内已冻结的平台内容；缺失平台不会从latest或当前CopyMatrix补齐。</p>
      </header>
      <section className="snapshot-copy-grid">
        {primary.map(({ platform, copy }) => copy
          ? <CopyCard copy={copy} key={platform} />
          : <MissingCopyCard platform={platform} key={platform} />)}
        {extras.map((copy) => <CopyCard copy={copy} key={copy.platform} />)}
      </section>
    </div>
  );
}

function CopyCard({ copy }: { copy: SnapshotCopyView }) {
  return (
    <article className="snapshot-copy-card">
      <header><span>{copy.platform || "未标记平台"}</span><strong>SNAPSHOT COPY</strong></header>
      <section><small>HOOK</small><h3>{copy.hook || "字段缺失"}</h3></section>
      <section><small>CAPTION</small><p>{copy.caption || "字段缺失"}</p></section>
      <section><small>HASHTAGS</small><div>{copy.hashtags.length > 0 ? copy.hashtags.map((tag) => <em key={tag}>{tag}</em>) : <span>缺失</span>}</div></section>
      <section><small>CTA</small><strong>{copy.cta || "字段缺失"}</strong></section>
    </article>
  );
}

function MissingCopyCard({ platform }: { platform: string }) {
  return (
    <article className="snapshot-copy-card snapshot-copy-card--missing">
      <header><span>{platform}</span><strong>MISSING</strong></header>
      <div className="snapshot-empty-evidence"><strong>平台文案缺失</strong><p>该Snapshot没有{platform}文案，不使用其他记录代替。</p></div>
    </article>
  );
}
