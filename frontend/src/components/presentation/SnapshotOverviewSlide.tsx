import type { PresentationSnapshot } from "../../types/presentationSnapshot";
import type { SnapshotPresentationView } from "./snapshotPresentationPayload";

export function SnapshotOverviewSlide({
  snapshot,
  view,
}: {
  snapshot: PresentationSnapshot;
  view: SnapshotPresentationView;
}) {
  const product = view.product;
  const strategy = view.strategy;
  const loop = [
    ["Product", Boolean(product)],
    ["Brief", Boolean(view.brief)],
    ["Strategy", Boolean(strategy)],
    ["Copy", view.copies.length > 0],
    ["Video", Boolean(view.video)],
    ["Artifact", Boolean(view.artifact)],
    ["Delivery", Boolean(view.publish)],
    ["Growth", view.campaigns.length > 0],
  ] as const;

  return (
    <div className="snapshot-slide snapshot-overview-slide">
      <section className="snapshot-slide-hero">
        <div>
          <span>01 · OVERVIEW</span>
          <h2>{product?.name || "Product信息缺失"}</h2>
          <p>{product?.description || "Snapshot未包含Product描述。"}</p>
        </div>
        <aside>
          <small>Snapshot Identity</small>
          <strong>#{snapshot.id}</strong>
          <code>{digestSummary(snapshot.digest)}</code>
          <span>不可变只读证据</span>
        </aside>
      </section>

      <section className="snapshot-overview-grid">
        <article className="snapshot-slide-card snapshot-product-card">
          <header><span>PRODUCT</span><strong>{product?.category || "分类缺失"}</strong></header>
          <FactGroup title="目标市场" values={product?.targetMarkets ?? []} />
          <FactGroup title="核心卖点" values={product?.sellingPoints ?? []} ordered />
        </article>

        <article className="snapshot-slide-card">
          <header><span>MARKETING BRIEF</span><strong>{view.brief ? `#${view.brief.id}` : "缺失"}</strong></header>
          {view.brief ? (
            <dl className="snapshot-facts">
              <Fact label="受众" value={view.brief.audience} />
              <Fact label="语言" value={view.brief.language} />
              <Fact label="平台" value={view.brief.platforms.join(" · ")} />
              <Fact label="语气" value={view.brief.tone} />
              <Fact label="目标" value={view.brief.objective} />
            </dl>
          ) : (
            <EmptyEvidence text="Snapshot明确记录MarketingBrief缺失，不从当前商品或其他记录补齐。" />
          )}
        </article>

        <article className="snapshot-slide-card snapshot-strategy-card">
          <header><span>STRATEGY</span><strong>{strategy ? `#${strategy.id}` : "缺失"}</strong></header>
          {strategy ? (
            <>
              <div className="snapshot-positioning">
                <small>定位</small>
                <p>{strategy.positioning || "定位字段缺失"}</p>
              </div>
              <FactGroup title="受众洞察" values={strategy.audienceInsights} ordered />
              <FactGroup title="营销角度" values={strategy.angles} ordered />
            </>
          ) : (
            <EmptyEvidence text="Snapshot未包含Strategy。" />
          )}
        </article>
      </section>

      <section className="snapshot-loop" aria-label="不可变闭环概览">
        <header><span>IMMUTABLE GROWTH LOOP</span><strong>完整闭环概览</strong></header>
        <div>
          {loop.map(([label, available], index) => (
            <div className={available ? "is-present" : "is-missing"} key={label}>
              <small>{String(index + 1).padStart(2, "0")}</small>
              <strong>{label}</strong>
              <span>{available ? "已快照" : "缺失"}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || "缺失"}</dd></div>;
}

function FactGroup({ title, values, ordered = false }: { title: string; values: string[]; ordered?: boolean }) {
  const List = ordered ? "ol" : "div";
  return (
    <div className="snapshot-fact-group">
      <small>{title}</small>
      {values.length > 0 ? (
        <List>{values.map((value) => ordered ? <li key={value}>{value}</li> : <span key={value}>{value}</span>)}</List>
      ) : <p>缺失</p>}
    </div>
  );
}

function EmptyEvidence({ text }: { text: string }) {
  return <div className="snapshot-empty-evidence"><strong>数据缺失</strong><p>{text}</p></div>;
}

function digestSummary(digest: string): string {
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}
